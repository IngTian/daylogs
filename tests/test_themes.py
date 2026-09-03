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

    A theme name in config.toml can go stale — a typo, or a Textual upgrade that
    drops it. Refusing to start over a cosmetic setting would be absurd, so this
    path falls back. The interactive path raises instead; see `check`.
    """
    assert themes.resolve("no-such-theme") == themes.DEFAULT
    assert themes.resolve("") == themes.DEFAULT
    assert themes.resolve(None) == themes.DEFAULT


def test_check_raises_on_an_unknown_name():
    """The typed path is the opposite of the config path: it must object, so the
    prompt can keep your text and let you fix it."""
    with pytest.raises(themes.ThemeError) as e:
        themes.check("gruvbax")
    assert "gruvbax" in str(e.value), "the rejection should quote what was typed"


def test_check_returns_the_name_it_accepted():
    assert themes.check("gruvbox") == "gruvbox"


def test_check_tolerates_surrounding_space():
    """Typed input, so it arrives however the user left it."""
    assert themes.check("  nord  ") == "nord"
