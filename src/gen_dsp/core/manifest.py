"""
Front-end-agnostic manifest for gen-dsp platform backends.

The Manifest captures everything a platform generator needs --
I/O counts, parameter metadata, buffer names -- without coupling
to any particular front-end (gen~ exports, future Python DSL, etc.).

Typical data flow:

    gen~ export -> parser -> ExportInfo -> manifest_from_export_info() -> Manifest
                                        -> project.py passes Manifest to platforms
"""

import json
import re
from dataclasses import dataclass, field

from typing import Any

from gen_dsp.version import __version__
from gen_dsp.core.parser import ExportInfo


@dataclass
class ParamInfo:
    """Metadata for a single parameter."""

    index: int
    name: str
    has_minmax: bool
    min: float
    max: float
    default: float

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict of this parameter's fields."""
        return {
            "index": self.index,
            "name": self.name,
            "has_minmax": self.has_minmax,
            "min": self.min,
            "max": self.max,
            "default": self.default,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ParamInfo":
        """Reconstruct a ``ParamInfo`` from a :meth:`to_dict` mapping."""
        return cls(
            index=d["index"],
            name=d["name"],
            has_minmax=d["has_minmax"],
            min=d["min"],
            max=d["max"],
            default=d["default"],
        )


@dataclass
class RemappedInput:
    """A signal input remapped to a parameter.

    When gen~ exports use signal-rate ``in`` objects for control data
    (e.g., pitch, gate), ``--inputs-as-params`` converts them to plugin
    parameters. The gen~ perform function still receives input buffers
    -- the bridge fills them with the parameter value each block.
    """

    gen_input_index: int  # original index in gen~'s input array
    input_name: str  # name from gen_kernel_innames[]
    param_index: int  # index in the expanded param list

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict of this remapping's fields."""
        return {
            "gen_input_index": self.gen_input_index,
            "input_name": self.input_name,
            "param_index": self.param_index,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RemappedInput":
        """Reconstruct a ``RemappedInput`` from a :meth:`to_dict` mapping."""
        return cls(
            gen_input_index=d["gen_input_index"],
            input_name=d["input_name"],
            param_index=d["param_index"],
        )


@dataclass
class Manifest:
    """Front-end-agnostic intermediate representation for platform backends."""

    gen_name: str
    num_inputs: int
    num_outputs: int
    params: list[ParamInfo] = field(default_factory=list)
    buffers: list[str] = field(default_factory=list)
    remapped_inputs: list[RemappedInput] = field(default_factory=list)
    source: str = "gen~"
    version: str = __version__

    @property
    def num_params(self) -> int:
        """Number of parameters (convenience for ``len(self.params)``)."""
        return len(self.params)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict of the manifest.

        ``remapped_inputs`` is omitted when empty, keeping the common
        (no-remap) ``manifest.json`` output compact.
        """
        d: dict[str, Any] = {
            "gen_name": self.gen_name,
            "num_inputs": self.num_inputs,
            "num_outputs": self.num_outputs,
            "params": [p.to_dict() for p in self.params],
            "buffers": self.buffers,
            "source": self.source,
            "version": self.version,
        }
        if self.remapped_inputs:
            d["remapped_inputs"] = [r.to_dict() for r in self.remapped_inputs]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Manifest":
        """Reconstruct a ``Manifest`` from a :meth:`to_dict` mapping."""
        return cls(
            gen_name=d["gen_name"],
            num_inputs=d["num_inputs"],
            num_outputs=d["num_outputs"],
            params=[ParamInfo.from_dict(p) for p in d.get("params", [])],
            buffers=d.get("buffers", []),
            remapped_inputs=[
                RemappedInput.from_dict(r) for r in d.get("remapped_inputs", [])
            ],
            source=d.get("source", "gen~"),
            version=d.get("version", __version__),
        )

    def to_json(self, indent: int = 2) -> str:
        """Serialize to a JSON string -- the content of a project's ``manifest.json``."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, text: str) -> "Manifest":
        """Parse a ``Manifest`` from a :meth:`to_json` string."""
        return cls.from_dict(json.loads(text))


# ---------------------------------------------------------------------------
# Parameter parsing from gen~ exports
# ---------------------------------------------------------------------------

# Regex to extract parameter blocks from gen~ export create() function.
# Matches the structured block:
#   pi = self->__commonstate.params + <index>;
#   pi->name = "<name>";
#   pi->defaultvalue = self->m_<varname>;
#   ...
#   pi->hasminmax = true|false;
#   pi->outputmin = <float>;
#   pi->outputmax = <float>;
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

# Regex to extract the member variable name from pi->defaultvalue = self->m_XXX;
_DEFAULT_VAR_RE = re.compile(r"pi->defaultvalue\s*=\s*self->(m_\w+)\s*;")

# Regex to extract initial values from reset(): m_XXX = ((int|t_sample)VALUE);
_MEMBER_INIT_RE = re.compile(r"(m_\w+)\s*=\s*\(\((?:int|t_sample)\)([\d.eE+\-]+)\)\s*;")


def _parse_member_init_values(content: str) -> dict[str, float]:
    """Parse initial member values from the reset() function.

    Extracts assignments like: m_bandwidth_21 = ((t_sample)0.5);
    Returns a dict mapping member name to numeric value.
    """
    values: dict[str, float] = {}
    for m in _MEMBER_INIT_RE.finditer(content):
        values[m.group(1)] = float(m.group(2))
    return values


def _parse_default_var_for_param(content: str, param_block_start: int) -> str | None:
    """Find the pi->defaultvalue member variable name near a param block.

    Searches forward from param_block_start for the defaultvalue assignment
    within the same parameter block (before the next 'pi = ' assignment).
    """
    # Search from the param block start to the next block or end
    next_block = content.find("pi = self->__commonstate.params", param_block_start + 1)
    region = (
        content[param_block_start:next_block]
        if next_block != -1
        else content[param_block_start:]
    )
    m = _DEFAULT_VAR_RE.search(region)
    return m.group(1) if m else None


def parse_params_from_export(export_info: ExportInfo) -> list[ParamInfo]:
    """Parse parameter metadata from a gen~ export's .cpp file.

    Returns an empty list if parsing fails or no params exist.
    """
    if not export_info.cpp_path or not export_info.cpp_path.exists():
        return []

    content = export_info.cpp_path.read_text(encoding="utf-8")

    # Build lookup of member variable initial values from reset()
    member_values = _parse_member_init_values(content)

    params = []
    for m in _PARAM_BLOCK_RE.finditer(content):
        output_min = float(m.group(4))
        output_max = float(m.group(5))

        # Try to extract the actual default value from pi->defaultvalue
        default = output_min  # fallback
        var_name = _parse_default_var_for_param(content, m.start())
        if var_name and var_name in member_values:
            raw_default = member_values[var_name]
            # Clamp to declared range -- gen~ initial values may exceed it
            default = max(output_min, min(output_max, raw_default))

        params.append(
            ParamInfo(
                index=int(m.group(1)),
                name=m.group(2),
                has_minmax=(m.group(3) == "true"),
                min=output_min,
                max=output_max,
                default=default,
            )
        )
    params.sort(key=lambda p: p.index)
    return params


def manifest_from_export_info(
    export_info: ExportInfo,
    buffers: list[str],
    version: str,
) -> "Manifest":
    """Build a Manifest from a parsed gen~ ExportInfo."""
    params = parse_params_from_export(export_info)
    return Manifest(
        gen_name=export_info.name,
        num_inputs=export_info.num_inputs,
        num_outputs=export_info.num_outputs,
        params=params,
        buffers=list(buffers),
        source="gen~",
        version=version,
    )


# ---------------------------------------------------------------------------
# Input-to-parameter remapping
# ---------------------------------------------------------------------------


def _sanitize_input_name(name: str) -> str:
    """Convert an input name to a valid C identifier for use as a param name.

    E.g. "c/m ratio" -> "c_m_ratio"
    """
    result = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    # Collapse multiple underscores
    result = re.sub(r"_+", "_", result).strip("_")
    if not result or not result[0].isalpha():
        result = "input_" + result
    return result


def apply_inputs_as_params(
    manifest: Manifest,
    input_names: list[str],
    remap_names: list[str] | None = None,
) -> Manifest:
    """Remap signal inputs to parameters.

    When ``remap_names`` is None (bare ``--inputs-as-params``), all signal
    inputs are remapped. When a list is given, only those named inputs are
    remapped.

    The returned manifest has reduced ``num_inputs`` and extra ``ParamInfo``
    entries appended for each remapped input. The ``remapped_inputs`` list
    records the mapping from gen~ input index to param index.

    Args:
        manifest: Original manifest with gen~'s real I/O counts.
        input_names: Input names from ``ExportInfo.input_names``.
        remap_names: Subset of input names to remap, or None for all.

    Returns:
        New Manifest with remapped inputs applied.

    Raises:
        ValueError: If a requested name is not in ``input_names``.
    """
    if not input_names:
        raise ValueError(
            "No input names found in gen~ export (gen_kernel_innames). "
            "Cannot remap inputs to parameters."
        )

    # Determine which inputs to remap
    if remap_names is None:
        # Remap all
        indices_to_remap = list(range(len(input_names)))
    else:
        indices_to_remap = []
        for rname in remap_names:
            try:
                idx = input_names.index(rname)
            except ValueError:
                raise ValueError(
                    f"Input name '{rname}' not found. "
                    f"Available input names: {input_names}"
                )
            indices_to_remap.append(idx)

    if not indices_to_remap:
        return manifest

    # Build new params list (copy existing, then append synthetic ones)
    new_params = list(manifest.params)
    remapped: list[RemappedInput] = []
    next_param_idx = len(new_params)

    for gen_idx in indices_to_remap:
        name = input_names[gen_idx]
        param_name = _sanitize_input_name(name)
        new_params.append(
            ParamInfo(
                index=next_param_idx,
                name=param_name,
                has_minmax=False,
                min=0.0,
                max=1.0,
                default=0.0,
            )
        )
        remapped.append(
            RemappedInput(
                gen_input_index=gen_idx,
                input_name=name,
                param_index=next_param_idx,
            )
        )
        next_param_idx += 1

    new_num_inputs = manifest.num_inputs - len(indices_to_remap)

    return Manifest(
        gen_name=manifest.gen_name,
        num_inputs=new_num_inputs,
        num_outputs=manifest.num_outputs,
        params=new_params,
        buffers=list(manifest.buffers),
        remapped_inputs=remapped,
        source=manifest.source,
        version=manifest.version,
    )


def _build_remap_defs(manifest: Manifest) -> list[str]:
    """Return raw KEY=VALUE define pairs for input-to-parameter remapping.

    Returns an empty list if no inputs are remapped.
    """
    if not manifest.remapped_inputs:
        return []

    # Total gen~ inputs (before remapping) = current num_inputs + remap count
    gen_total = manifest.num_inputs + len(manifest.remapped_inputs)

    defs = [
        f"REMAP_INPUT_COUNT={len(manifest.remapped_inputs)}",
        f"REMAP_GEN_TOTAL_INPUTS={gen_total}",
    ]
    for i, ri in enumerate(manifest.remapped_inputs):
        defs.append(f"REMAP_INPUT_{i}_GEN_IDX={ri.gen_input_index}")
        defs.append(f"REMAP_INPUT_{i}_PARAM_IDX={ri.param_index}")
        # Escape the name for a C string literal in a compile define
        escaped = ri.input_name.replace("\\", "\\\\").replace('"', '\\"')
        defs.append(f'REMAP_INPUT_{i}_NAME="{escaped}"')

    return defs


def build_remap_defines(manifest: Manifest) -> str:
    """Build CMake compile definition lines for input-to-parameter remapping.

    Returns an empty string if no inputs are remapped, or newline+indent
    separated definition strings suitable for CMake target_compile_definitions().

    Follows the same pattern as ``build_midi_defines()`` in ``midi.py``.
    """
    defs = _build_remap_defs(manifest)
    if not defs:
        return ""
    return "\n    ".join(defs)


def build_remap_defines_make(
    manifest: Manifest,
    flag_vars: str | list[str] = "FLAGS",
) -> str:
    """Build Make-style compile flags for input-to-parameter remapping.

    Returns an empty string if no inputs are remapped, or newline-separated
    ``FLAG_VAR += -DKEY=VALUE`` lines suitable for Makefile templates.

    ``flag_vars`` can be a single variable name or a list (e.g. ``["CFLAGS", "CPPFLAGS"]``)
    to emit defines for multiple flag variables.
    """
    defs = _build_remap_defs(manifest)
    if not defs:
        return ""
    if isinstance(flag_vars, str):
        flag_vars = [flag_vars]
    lines = []
    for var in flag_vars:
        for d in defs:
            lines.append(f"{var} += -D{d}")
    return "\n".join(lines)
