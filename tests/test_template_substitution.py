"""Tests for the strict template substitution helper (R10).

``substitute_strict`` replaces ``Template.safe_substitute`` across all platform
generators so that a typo'd or missing ``$placeholder`` fails loudly at project
generation time instead of leaking a literal ``$token`` into a broken build
file. A literal ``$`` must be written ``$$``.
"""

from string import Template

import pytest

from gen_dsp.errors import ProjectError
from gen_dsp.platforms.base import substitute_strict


class TestSubstituteStrict:
    def test_substitutes_provided_vars(self):
        result = substitute_strict(
            Template("hello $name, version $ver"),
            label="t",
            name="world",
            ver="1.0",
        )
        assert result == "hello world, version 1.0"

    def test_braced_placeholder(self):
        result = substitute_strict(Template("${greeting}!"), label="t", greeting="hi")
        assert result == "hi!"

    def test_escaped_dollar_passes_through(self):
        # '$$' is the escape for a literal '$' (make/CMake variables rely on this).
        result = substitute_strict(
            Template("make var $$(CC) and py $py"), label="t", py="X"
        )
        assert result == "make var $(CC) and py X"

    def test_non_string_values_stringified(self):
        result = substitute_strict(Template("n=$n"), label="t", n=42)
        assert result == "n=42"

    def test_missing_variable_raises_project_error(self):
        with pytest.raises(ProjectError) as exc:
            substitute_strict(
                Template("$present $missing"), label="my.txt", present="x"
            )
        msg = str(exc.value)
        assert "my.txt" in msg
        assert "missing" in msg  # names the offending variable
        assert "present" in msg  # lists what was provided

    def test_missing_variable_mentions_label(self):
        with pytest.raises(ProjectError, match="CMakeLists template"):
            substitute_strict(Template("$typo"), label="CMakeLists template")

    def test_malformed_dollar_token_raises_project_error(self):
        # A bare '$' that is not '$$', '$name', or '${name}' is malformed.
        with pytest.raises(ProjectError) as exc:
            substitute_strict(Template("cost is $ 5"), label="prices.txt")
        msg = str(exc.value)
        assert "prices.txt" in msg
        assert "$$" in msg  # hints at the escape fix

    def test_unprovided_with_no_vars_reports_none(self):
        with pytest.raises(ProjectError, match="provided: none"):
            substitute_strict(Template("$x"), label="t")

    def test_extra_unused_vars_are_ignored(self):
        # Providing more than the template needs is fine (no error).
        result = substitute_strict(Template("$a"), label="t", a="1", unused="2")
        assert result == "1"
