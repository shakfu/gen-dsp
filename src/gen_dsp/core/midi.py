"""
MIDI-to-CV auto-detection and mapping for gen-dsp instruments.

Scans gen~ parameter names to detect MIDI-mappable parameters (gate, freq, vel)
and produces compile-time constants for the platform wrappers.

Only activates for 0-input (generator) plugins. Effects are never MIDI-mapped.
"""

from dataclasses import dataclass
from typing import Optional

from gen_dsp.core.manifest import Manifest

# Parameter name patterns for auto-detection (case-sensitive, gen~ uses lowercase)
_GATE_NAMES = {"gate"}
_FREQ_NAMES = {"freq", "frequency", "pitch"}
_VEL_NAMES = {"vel", "velocity"}


@dataclass
class MidiMapping:
    """Compile-time MIDI-to-parameter mapping for instrument plugins.

    Attributes:
        enabled: Whether MIDI note handling code should be generated.
        gate_idx: Parameter index for gate (None if not mapped).
        freq_idx: Parameter index for frequency (None if not mapped).
        vel_idx: Parameter index for velocity (None if not mapped).
        freq_unit: "hz" for mtof conversion, "midi" for raw note number.
    """

    enabled: bool
    gate_idx: Optional[int] = None
    freq_idx: Optional[int] = None
    vel_idx: Optional[int] = None
    freq_unit: str = "hz"
    num_voices: int = 1


def detect_midi_mapping(
    manifest: Manifest,
    no_midi: bool = False,
    midi_gate: Optional[str] = None,
    midi_freq: Optional[str] = None,
    midi_vel: Optional[str] = None,
    midi_freq_unit: str = "hz",
) -> MidiMapping:
    """Detect MIDI parameter mapping from a manifest.

    Detection rules:
    1. Only for 0-input plugins (generators). Effects -> disabled.
    2. If no_midi is True -> disabled.
    3. If any explicit --midi-* name is provided, use those (implies enabled).
    4. Otherwise auto-detect by scanning param names for known patterns.
       Gate is required for auto-detection to activate.

    Args:
        manifest: The plugin manifest with param metadata.
        no_midi: Force MIDI off.
        midi_gate: Explicit gate param name override.
        midi_freq: Explicit freq param name override.
        midi_vel: Explicit vel param name override.
        midi_freq_unit: "hz" (default, mtof conversion) or "midi" (raw note).

    Returns:
        MidiMapping with detected/configured indices.
    """
    disabled = MidiMapping(enabled=False)

    # Effects never get MIDI
    if manifest.num_inputs > 0:
        return disabled

    # Explicit opt-out
    if no_midi:
        return disabled

    # Build name->index lookup
    param_by_name: dict[str, int] = {p.name: p.index for p in manifest.params}

    # Check for explicit overrides
    has_explicit = (
        midi_gate is not None or midi_freq is not None or midi_vel is not None
    )

    if has_explicit:
        gate_idx = param_by_name.get(midi_gate) if midi_gate else None
        freq_idx = param_by_name.get(midi_freq) if midi_freq else None
        vel_idx = param_by_name.get(midi_vel) if midi_vel else None
        return MidiMapping(
            enabled=True,
            gate_idx=gate_idx,
            freq_idx=freq_idx,
            vel_idx=vel_idx,
            freq_unit=midi_freq_unit,
        )

    # Auto-detection: scan param names
    gate_idx = _find_param_index(param_by_name, _GATE_NAMES)

    # Gate is required for auto-detection
    if gate_idx is None:
        return disabled

    freq_idx = _find_param_index(param_by_name, _FREQ_NAMES)
    vel_idx = _find_param_index(param_by_name, _VEL_NAMES)

    return MidiMapping(
        enabled=True,
        gate_idx=gate_idx,
        freq_idx=freq_idx,
        vel_idx=vel_idx,
        freq_unit=midi_freq_unit,
    )


def build_midi_defines(midi_mapping: Optional[MidiMapping]) -> str:
    """Build CMake compile definition lines for a MIDI mapping.

    Returns an empty string if MIDI is disabled, or newline+indent-separated
    definition strings like "MIDI_ENABLED=1\\n    MIDI_GATE_IDX=5".

    Shared by all CMake-based platforms (CLAP, VST3, etc.).
    """
    if midi_mapping is None or not midi_mapping.enabled:
        return ""

    defs = ["MIDI_ENABLED=1"]
    if midi_mapping.gate_idx is not None:
        defs.append(f"MIDI_GATE_IDX={midi_mapping.gate_idx}")
    if midi_mapping.freq_idx is not None:
        defs.append(f"MIDI_FREQ_IDX={midi_mapping.freq_idx}")
        freq_hz = 1 if midi_mapping.freq_unit == "hz" else 0
        defs.append(f"MIDI_FREQ_UNIT_HZ={freq_hz}")
    if midi_mapping.vel_idx is not None:
        defs.append(f"MIDI_VEL_IDX={midi_mapping.vel_idx}")
    if midi_mapping.num_voices > 1:
        defs.append(f"NUM_VOICES={midi_mapping.num_voices}")
    return "\n    ".join(defs)


def _find_param_index(param_by_name: dict[str, int], names: set[str]) -> Optional[int]:
    """Find the first matching param index from a set of candidate names."""
    for name in names:
        if name in param_by_name:
            return param_by_name[name]
    return None
