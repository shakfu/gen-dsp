"""
Custom exceptions for gen_dsp.
"""


class GenExtError(Exception):
    """Base exception for gen_dsp errors."""


class ParseError(GenExtError):
    """Error parsing gen~ export files."""


class ValidationError(GenExtError):
    """Error validating configuration or inputs."""


class ProjectError(GenExtError):
    """Error creating or managing project."""


class BuildError(GenExtError):
    """Error during build process."""


class PatchError(GenExtError):
    """Error applying patches."""
