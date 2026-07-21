"""Shared identifier-naming helpers.

The per-name sanitizers (``Platform.sanitize_c_identifier``,
``SuperColliderPlatform._sanitize_sc_arg``, ``_sanitize_input_name``) coerce one
arbitrary string into one valid target-language identifier. They cannot see
their siblings, so two distinct source names that differ only in punctuation
both reduce to the same identifier. This module owns the group-level pass that
resolves those collisions.

It lives in ``core`` rather than ``platforms`` because both layers need it and
``platforms.base`` already imports from ``core.manifest``.
"""

from collections.abc import Iterable, Sequence


def uniquify_identifiers(
    names: Sequence[str], taken: Iterable[str] | None = None
) -> list[str]:
    """Disambiguate duplicate identifiers by appending a numeric suffix.

    Distinct source names that differ only in punctuation (``"a b"`` and
    ``"a-b"``) both sanitize to ``a_b``. Emitting both would produce duplicate
    C members, duplicate SuperCollider argument names, or duplicate
    ``lv2:symbol`` values. This pass keeps the first occurrence unchanged and
    renames later ones to ``a_b_2``, ``a_b_3``, ... , skipping any suffix that
    is itself already in use.

    ``taken`` seeds the set of names already spoken for by something outside
    ``names`` -- the ``in<i>`` audio-input arguments an SC UGen shares with its
    parameter list, the ``in<i>``/``out<i>``/``midi_in`` port symbols an LV2
    plugin shares with its control ports, or the pre-existing parameters that
    remapped inputs are appended to.

    The first occurrence is deliberately left untouched so that the
    overwhelmingly common no-collision case produces byte-identical output to
    before this pass existed.
    """
    taken_set = set(taken or ())
    used = set(names) | taken_set
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        if name not in seen and name not in taken_set:
            seen.add(name)
            result.append(name)
            continue
        counter = 2
        while f"{name}_{counter}" in used or f"{name}_{counter}" in seen:
            counter += 1
        unique = f"{name}_{counter}"
        seen.add(unique)
        used.add(unique)
        result.append(unique)
    return result
