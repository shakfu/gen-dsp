"""
Custom exceptions for gen_ext.
"""


class GenExtError(Exception):
    """Base exception for gen_ext errors."""

    pass


class ParseError(GenExtError):
    """Error parsing gen~ export files."""

    pass


class ValidationError(GenExtError):
    """Error validating configuration or inputs."""

    pass


class ProjectError(GenExtError):
    """Error creating or managing project."""

    pass


class BuildError(GenExtError):
    """Error during build process."""

    pass


class PatchError(GenExtError):
    """Error applying patches."""

    pass


class TemplateError(GenExtError):
    """Error accessing or processing templates."""

    pass
