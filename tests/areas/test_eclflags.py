"""`Row.value_text` reports constants, and `computed` only for a non-constant write."""
import types

from tools.areas import eclflags


def _row(*values):
    refs = {0x4A9E: [
        types.SimpleNamespace(script=f"ECL{i}", write=True, value=v)
        for i, v in enumerate(values)]}
    return eclflags.Row(0x4A9E, refs, set(), {})


def test_two_sites_writing_the_same_constant_report_it():
    assert _row(1, 1).value_text == "1"


def test_different_constants_are_listed():
    assert _row(1, 2).value_text == "1, 2"


def test_a_non_constant_write_is_computed():
    assert _row(None).value_text == "computed"


def test_a_constant_and_a_non_constant_write_list_both():
    assert _row(1, 1, None).value_text == "1, computed"


def test_the_4a81_name_carries_the_two_routes_note():
    assert eclflags.NOTES[0x4A81] in eclflags.known_names()[0x4A81]
