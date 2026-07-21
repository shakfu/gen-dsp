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
from gen_dsp.platforms.lv2 import Lv2Platform
from gen_dsp.platforms.supercollider import SuperColliderPlatform
from gen_dsp.core.manifest import (
    Manifest,
    ParamInfo,
    _sanitize_input_name,
    apply_inputs_as_params,
)


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


class TestReservedWords:
    """Sanitized names must not collide with target-language keywords.

    This applies to SuperCollider but deliberately NOT to
    ``sanitize_c_identifier``: its only caller emits ``lv2:symbol``, and the
    LV2 spec constrains a symbol to the character-class pattern
    ``[_a-zA-Z][_a-zA-Z0-9]*`` (lv2core.ttl), which ``float`` satisfies. The
    accompanying prose notes only that this class "is, among other things, a
    valid C identifier" -- it does not reserve keywords. Since a symbol is a
    strong identifier that hosts persist for automation and presets, rewriting
    it would break saved sessions to fix nothing.
    """

    def test_c_keywords_pass_through_unchanged(self):
        # Not a gap: see the class docstring. If a future backend emits a param
        # name into real C/C++ source, it must escape keywords at that site.
        for kw in ["float", "int", "class", "switch", "register", "operator"]:
            assert sanitize_c(kw) == kw

    def test_c_keywords_are_valid_lv2_symbols(self):
        # The normative LV2 constraint, restated as the guard that matters.
        lv2_symbol = re.compile(r"^[_a-zA-Z][_a-zA-Z0-9]*$")
        for kw in ["float", "class", "operator"]:
            assert lv2_symbol.match(sanitize_c(kw)), kw

    def test_sc_keywords_are_escaped(self):
        for kw in ["var", "arg", "this", "nil", "true", "false"]:
            result = sanitize_sc(kw)
            assert result != kw, f"{kw!r} passed through as an SC keyword"
            assert "a" <= result[0] <= "z", (kw, result)
            assert _C_IDENTIFIER.match(result), (kw, result)

    def test_sc_non_keywords_unaffected(self):
        for name in ["cutoff", "argument", "variance", "nilpotent"]:
            assert sanitize_sc(name) == name


class TestUniquify:
    """Platform.uniquify_identifiers disambiguates post-sanitization collisions."""

    def test_distinct_names_unchanged(self):
        assert Platform.uniquify_identifiers(["a", "b", "c"]) == ["a", "b", "c"]

    def test_duplicates_get_numeric_suffix(self):
        assert Platform.uniquify_identifiers(["a", "a", "a"]) == ["a", "a_2", "a_3"]

    def test_first_occurrence_is_preserved(self):
        # The common case must not shift, or every existing generated project
        # would churn.
        assert Platform.uniquify_identifiers(["gain", "freq"]) == ["gain", "freq"]

    def test_suffix_skips_names_already_present(self):
        # "a_2" is taken by a real param, so the duplicate must land on "a_3".
        assert Platform.uniquify_identifiers(["a", "a_2", "a"]) == ["a", "a_2", "a_3"]

    def test_taken_seed_is_respected(self):
        # SC seeds the audio-input arg names so a param cannot shadow them.
        assert Platform.uniquify_identifiers(["in0"], taken={"in0"}) == ["in0_2"]

    def test_empty_list(self):
        assert Platform.uniquify_identifiers([]) == []


class TestCollisionsAreResolved:
    """The end-to-end defect: punctuation-only differences must not collapse."""

    def test_c_identifier_collisions(self):
        # All four sanitize to "a_b" individually.
        names = ["a b", "a-b", "a/b", "a.b"]
        sanitized = [sanitize_c(n) for n in names]
        assert len(set(sanitized)) == 1, "precondition: these collide"
        assert len(set(Platform.uniquify_identifiers(sanitized))) == len(names)

    def test_input_name_collisions(self):
        names = ["a  b", "a-b", "a/b"]
        sanitized = [_sanitize_input_name(n) for n in names]
        assert len(set(sanitized)) == 1, "precondition: these collide"
        assert len(set(Platform.uniquify_identifiers(sanitized))) == len(names)

    def test_empty_and_symbol_input_names_collide(self):
        # Both reduce to "input_".
        sanitized = [_sanitize_input_name(n) for n in ["", "!!!"]]
        assert len(set(sanitized)) == 1, "precondition: these collide"
        assert len(set(Platform.uniquify_identifiers(sanitized))) == 2


class TestGeneratorsResolveCollisions:
    """The generators must not emit duplicate identifiers end-to-end."""

    @staticmethod
    def _params(*names):
        return [
            ParamInfo(index=i, name=n, has_minmax=True, min=0.0, max=1.0, default=0.5)
            for i, n in enumerate(names)
        ]

    @staticmethod
    def _lv2_symbols(tmp_path, params, num_inputs=1, num_outputs=1, midi=False):
        Lv2Platform()._generate_plugin_ttl(
            output_dir=tmp_path,
            lib_name="collide",
            plugin_uri="urn:test:collide",
            num_inputs=num_inputs,
            num_outputs=num_outputs,
            num_params=len(params),
            params=params,
            midi_enabled=midi,
        )
        ttl = (tmp_path / "collide.ttl").read_text()
        return re.findall(r'lv2:symbol "([^"]+)"', ttl)

    @staticmethod
    def _sc_arg_names(tmp_path, params, num_inputs=2, num_outputs=1):
        SuperColliderPlatform()._generate_sc_class(
            output_dir=tmp_path,
            lib_name="collide",
            ugen_name="Collide",
            num_inputs=num_inputs,
            num_outputs=num_outputs,
            num_params=len(params),
            params=params,
        )
        sc = (tmp_path / "Collide.sc").read_text()
        arglist = re.search(r"\*ar \{ \|([^|]*)\|", sc).group(1)
        return [a.split("=")[0].strip() for a in arglist.split(",")]

    def test_lv2_symbols_unique(self, tmp_path):
        symbols = self._lv2_symbols(
            tmp_path, self._params("a b", "a-b", "a/b", "float")
        )
        assert len(symbols) == len(set(symbols)), symbols
        # "float" is a spec-valid lv2:symbol and must be left alone.
        assert "float" in symbols

    def test_lv2_param_cannot_shadow_audio_port(self, tmp_path):
        symbols = self._lv2_symbols(tmp_path, self._params("in0", "out0"))
        assert len(symbols) == len(set(symbols)), symbols

    def test_lv2_param_cannot_shadow_midi_port(self, tmp_path):
        symbols = self._lv2_symbols(tmp_path, self._params("midi_in"), midi=True)
        assert len(symbols) == len(set(symbols)), symbols

    def test_sc_arg_names_unique(self, tmp_path):
        names = self._sc_arg_names(tmp_path, self._params("a b", "a-b", "in0", "var"))
        assert len(names) == len(set(names)), names
        assert "var" not in names, "SC keyword emitted as an arg name"

    def test_remapped_inputs_do_not_collide(self):
        manifest = Manifest(
            gen_name="remap",
            num_inputs=3,
            num_outputs=1,
            params=self._params("gain"),
            buffers=[],
        )
        out = apply_inputs_as_params(manifest, ["a b", "a-b", "gain"])
        names = [p.name for p in out.params]
        assert len(names) == len(set(names)), names


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
