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
        return cls(
            index=d["index"],
            name=d["name"],
            has_minmax=d["has_minmax"],
            min=d["min"],
            max=d["max"],
            default=d["default"],
        )


@dataclass
class Manifest:
    """Front-end-agnostic intermediate representation for platform backends."""

    gen_name: str
    num_inputs: int
    num_outputs: int
    params: list[ParamInfo] = field(default_factory=list)
    buffers: list[str] = field(default_factory=list)
    source: str = "gen~"
    version: str = "0.8.0"

    @property
    def num_params(self) -> int:
        return len(self.params)

    def to_dict(self) -> dict[str, Any]:
        return {
            "gen_name": self.gen_name,
            "num_inputs": self.num_inputs,
            "num_outputs": self.num_outputs,
            "params": [p.to_dict() for p in self.params],
            "buffers": self.buffers,
            "source": self.source,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Manifest":
        return cls(
            gen_name=d["gen_name"],
            num_inputs=d["num_inputs"],
            num_outputs=d["num_outputs"],
            params=[ParamInfo.from_dict(p) for p in d.get("params", [])],
            buffers=d.get("buffers", []),
            source=d.get("source", "gen~"),
            version=d.get("version", "0.8.0"),
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, text: str) -> "Manifest":
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
