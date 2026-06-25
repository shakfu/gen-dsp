"""Single source of truth for the gen-dsp package version.

Kept as a dependency-free leaf module so any module (including those imported
during ``gen_dsp/__init__.py`` execution) can read the version without risking
a circular import.
"""

__version__ = "0.3.0"
