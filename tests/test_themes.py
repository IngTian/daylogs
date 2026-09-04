"""The theme list is Textual's, not ours — which is the point, and the risk.

daylogs does not define palettes. `app.tcss` uses only Textual design tokens
(`$surface`, `$accent`, `$text-muted`, …), so setting `App.theme` re-themes every
border, background and muted line with no stylesheet of our own. Textual ships
around twenty maintained themes, so hand-rolling a set would be rebuilding a wheel.

The risk that buys is that the names belong to a dependency. If Textual renames or
drops the one we default to, the app starts on a name that does not exist. That is
what `test_the_default_theme_exists` is for: it fails on upgrade rather than in use.
"""

import pytest

from daylogs.tui import themes


def test_the_default_theme_exists():
    """Guards the dependency, not our code.

    `DEFAULT` is a string we chose from a list Textual owns. A Textual upgrade that
    renames or removes it would otherwise surface as a first-run failure for a real
    user; here it surfaces as a red test.
    """
    assert themes.DEFAULT in themes.names(), (
        f"{themes.DEFAULT!r} is no longer a Textual theme — available: {themes.names()}"
    )


def test_names_are_sorted_and_non_empty():
    names = themes.names()
    assert names, "no themes at all — the Textual import is probably wrong"
    assert list(names) == sorted(names), "completion offers these in order, so sort them"


def test_the_well_known_themes_are_offered():
    """A spot-check that we are reading the real registry and not an empty stub."""
    names = set(themes.names())
    for expected in ("gruvbox", "nord", "tokyo-night", "dracula", "monokai"):
        assert expected in names, f"{expected} missing from {sorted(names)}"


def test_resolve_accepts_a_known_name():
    assert themes.resolve("nord") == "nord"


def test_resolve_falls_back_rather_than_raising():
    """Reading config must never be able to stop the app starting.

    A theme name in config.toml can go stale — a typo, or a Textual upgrade that drops
    it. Refusing to start over a cosmetic setting would be absurd, so this path falls
    back. It is the only validator: `T` is a picker, so every name it can produce came
    out of `names()` and there is no typed theme input left to reject.
    """
    assert themes.resolve("no-such-theme") == themes.DEFAULT
    assert themes.resolve("") == themes.DEFAULT
    assert themes.resolve(None) == themes.DEFAULT


# ── the picker's window ──────────────────────────────────────────────────
# `strip` is what answers "what are my options" in one row. Pure, so it is tested here
# rather than through the app: it is width arithmetic, and width arithmetic is where a
# panel silently sheds content.

NAMES = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf")


def test_the_cursor_is_marked_with_characters():
    """Not colour. The cursor sits on a name whose own colours are changing under it —
    highlighting is the one signal that cannot be trusted in this widget."""
    out = themes.strip(NAMES, 2, 80)
    assert "▸charlie◂" in out


def test_neighbours_on_both_sides_are_offered():
    """Both, so `←` and `→` each show you what they will reach. Growing rightward first
    is deliberate; growing *only* rightward would hide half the list."""
    out = themes.strip(NAMES, 3, 80)
    assert "charlie" in out, f"nothing to the left: {out!r}"
    assert "echo" in out, f"nothing to the right: {out!r}"


@pytest.mark.parametrize("width", [20, 30, 40, 60, 80, 110, 200])
@pytest.mark.parametrize("index", [0, 3, 6])
def test_the_window_never_exceeds_the_width(width, index):
    """The panel is the budget. One column over and the row wraps, doubling the picker's
    height and pushing the tab's content up by three rows mid-preview."""
    out = themes.strip(NAMES, index, width)
    assert len(out) <= width, f"{len(out)} columns in {width}: {out!r}"


def test_a_width_too_small_for_even_one_name_still_shows_the_selection():
    """Better to overflow by the length of one name than to render an empty picker: the
    selected name is the one thing the widget exists to say."""
    out = themes.strip(NAMES, 2, 4)
    assert "charlie" in out


def test_more_room_shows_more_options():
    assert len(themes.strip(NAMES, 3, 30)) < len(themes.strip(NAMES, 3, 80))


def test_the_full_list_needs_no_ellipsis():
    out = themes.strip(NAMES, 3, 200)
    assert "…" not in out
    for n in NAMES:
        assert n in out


def test_a_truncated_side_says_so():
    """Without it the window reads as the whole list, and `→` appears to do nothing at
    the edge of what is drawn."""
    out = themes.strip(NAMES, 0, 30)
    assert out.endswith("…"), out
    assert not out.startswith("…"), "there is nothing to the left of the first name"
    out = themes.strip(NAMES, 6, 30)
    assert out.startswith("…"), out
    assert not out.endswith("…"), "there is nothing to the right of the last name"


def test_an_empty_list_renders_nothing_rather_than_raising():
    """Reachable only if Textual ships with no themes at all, which is why it returns
    rather than asserting — a cosmetic setting must not be able to stop the app."""
    assert themes.strip((), 0, 80) == ""


@pytest.mark.parametrize("index", [-5, -1, 7, 999])
def test_an_index_outside_the_list_is_clamped(index):
    """The widget wraps with `%` so it cannot get here, which is exactly why the pure
    function guards it: the next caller has no such guarantee, and an IndexError inside a
    repaint takes the app down over a theme."""
    out = themes.strip(NAMES, index, 80)
    assert "▸" in out, f"no selection rendered for index {index}: {out!r}"
