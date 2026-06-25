"""Edge-case tests for the three parameter/identifier sanitizers.

These functions coerce arbitrary parameter and input names (which, via the
graph frontend, may be arbitrary user strings) into valid target-language
identifiers. They run on the critical path for every platform, so their
edge-case behavior is pinned here:

- ``Platform.sanitize_c_identifier`` (shared C identifier; used by LV2 etc.)
- ``SuperColliderPlatform._sanitize_sc_arg`` (SC method-argument names)
- ``_sanitize_input_name`` (input-as-param names in the manifest IR)

The three intentionally differ (underscore collapsing, leading-underscore
handling, fallback prefix), so the divergences are documented explicitly.
"""

import re

from gen_dsp.platforms.base import Platform
from gen_dsp.platforms.supercollider import SuperColliderPlatform
from gen_dsp.core.manifest import _sanitize_input_name


sanitize_c = Platform.sanitize_c_identifier
sanitize_sc = SuperColliderPlatform._sanitize_sc_arg


_C_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class TestSanitizeCIdentifier:
    """Platform.sanitize_c_identifier -> valid C identifier."""

    def test_empty_falls_back_to_param(self):
        assert sanitize_c("") == "param"

    def test_leading_digit_prefixed_with_underscore(self):
        assert sanitize_c("1abc") == "_1abc"

    def test_pure_digits(self):
        assert sanitize_c("123") == "_123"

    def test_unicode_replaced(self):
        # Non-ASCII letters are not in [a-zA-Z0-9_]; each becomes one '_'.
        assert sanitize_c("café") == "caf_"

    def test_all_symbols(self):
        # Symbol-only names reduce to underscores -- still a valid C identifier.
        assert sanitize_c("!!!") == "___"

    def test_spaces_become_underscores(self):
        assert sanitize_c("a b") == "a_b"

    def test_underscores_not_collapsed(self):
        # Unlike _sanitize_input_name, runs of underscores are preserved.
        assert sanitize_c("a  b") == "a__b"

    def test_leading_and_trailing_underscores_preserved(self):
        assert sanitize_c("_x_") == "_x_"

    def test_dotted_name(self):
        assert sanitize_c("freq.amount") == "freq_amount"

    def test_valid_identifier_passes_through(self):
        assert sanitize_c("cutoff") == "cutoff"

    def test_output_is_always_valid_c_identifier(self):
        for name in ["", "1abc", "café", "!!!", "_x_", "a  b", "123", "p.q"]:
            assert _C_IDENTIFIER.match(sanitize_c(name)), name


class TestSanitizeScArg:
    """SuperColliderPlatform._sanitize_sc_arg -> SC arg name (lowercase start)."""

    def test_empty_falls_back_to_param(self):
        assert sanitize_sc("") == "param"

    def test_uppercase_first_lowercased(self):
        assert sanitize_sc("Freq") == "freq"

    def test_only_first_char_lowercased(self):
        assert sanitize_sc("ABC") == "aBC"

    def test_leading_digit_prefixed(self):
        assert sanitize_sc("1abc") == "p_1abc"

    def test_pure_digits(self):
        assert sanitize_sc("123") == "p_123"

    def test_unicode_replaced(self):
        assert sanitize_sc("café") == "caf_"

    def test_uppercase_unicode(self):
        assert sanitize_sc("Café") == "caf_"

    def test_all_symbols_prefixed(self):
        # Regression: symbol-only names reduce to leading underscores, which are
        # invalid SC arg names -- must be prefixed to start with a letter.
        assert sanitize_sc("!!!") == "p____"

    def test_leading_underscore_prefixed(self):
        # Regression: a name starting with '_' is invalid as an SC arg.
        assert sanitize_sc("_x_") == "p__x_"

    def test_dotted_name(self):
        assert sanitize_sc("freq.amount") == "freq_amount"

    def test_valid_lowercase_passes_through(self):
        assert sanitize_sc("cutoff") == "cutoff"

    def test_output_always_starts_with_lowercase_letter(self):
        # SC requires arg names to begin with a lowercase letter.
        for name in ["", "Freq", "1abc", "café", "!!!", "_x_", "123", "ABC", "_"]:
            result = sanitize_sc(name)
            assert result, name
            assert "a" <= result[0] <= "z", (name, result)
            assert _C_IDENTIFIER.match(result), (name, result)


class TestSanitizeInputName:
    """_sanitize_input_name -> C identifier with alpha first char."""

    def test_docstring_example(self):
        assert _sanitize_input_name("c/m ratio") == "c_m_ratio"

    def test_empty_falls_back_to_input_prefix(self):
        assert _sanitize_input_name("") == "input_"

    def test_leading_digit_gets_input_prefix(self):
        # First char must be alpha (not just non-digit), so '_' prefix differs.
        assert _sanitize_input_name("1abc") == "input_1abc"

    def test_pure_digits(self):
        assert _sanitize_input_name("123") == "input_123"

    def test_all_symbols_collapse_to_input_prefix(self):
        # Symbols -> underscores -> collapsed -> stripped to empty -> prefixed.
        assert _sanitize_input_name("!!!") == "input_"

    def test_underscores_collapsed(self):
        # Unlike the other two sanitizers, runs of underscores collapse to one.
        assert _sanitize_input_name("a  b") == "a_b"

    def test_leading_trailing_underscores_stripped(self):
        assert _sanitize_input_name("_x_") == "x"

    def test_unicode_trailing_underscore_stripped(self):
        # "café" -> "caf_" -> collapsed -> stripped -> "caf"
        assert _sanitize_input_name("café") == "caf"

    def test_valid_name_passes_through(self):
        assert _sanitize_input_name("gain") == "gain"

    def test_output_always_starts_with_alpha(self):
        for name in ["", "1abc", "café", "!!!", "_x_", "123", "c/m ratio"]:
            result = _sanitize_input_name(name)
            assert result[0].isalpha(), (name, result)
            assert _C_IDENTIFIER.match(result), (name, result)


class TestSanitizerDivergences:
    """Pin the intended differences between the three sanitizers."""

    def test_leading_underscore_handling_differs(self):
        # C identifier keeps it; SC prefixes it; input-name strips it.
        assert sanitize_c("_x_") == "_x_"
        assert sanitize_sc("_x_") == "p__x_"
        assert _sanitize_input_name("_x_") == "x"

    def test_underscore_collapsing_differs(self):
        # Only _sanitize_input_name collapses runs of underscores.
        assert sanitize_c("a  b") == "a__b"
        assert sanitize_sc("a  b") == "a__b"
        assert _sanitize_input_name("a  b") == "a_b"

    def test_empty_fallbacks_differ(self):
        assert sanitize_c("") == "param"
        assert sanitize_sc("") == "param"
        assert _sanitize_input_name("") == "input_"
