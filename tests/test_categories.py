from daybook.categories import (
    BUILTIN,
    FALLBACK_SLUG,
    PALETTE,
    all_categories,
    auto_color,
    get,
    slugs,
)
from daybook.config import load_config


def test_nine_builtins_no_income_category():
    assert len(BUILTIN) == 9
    assert FALLBACK_SLUG in slugs()
    assert "employment" not in slugs()


def test_every_builtin_has_display_and_hex_colour():
    for c in BUILTIN:
        assert c.display
        assert c.color.startswith("#") and len(c.color) == 7


def test_get_returns_none_for_unknown():
    assert get("grocery").display
    assert get("nonexistent") is None


def test_config_extends_builtins(tmp_path):
    (tmp_path / "config.toml").write_text(
        "[[category]]\nslug = 'gym'\ndisplay = 'Gym'\ncolor = '#9ba068'\n"
    )
    cfg = load_config(tmp_path)
    assert "gym" in slugs(cfg)
    assert get("gym", cfg).display == "Gym"
    assert len(all_categories(cfg)) == len(BUILTIN) + 1


def test_config_entry_without_colour_gets_auto_colour(tmp_path):
    (tmp_path / "config.toml").write_text("[[category]]\nslug = 'gym'\n")
    cfg = load_config(tmp_path)
    cat = get("gym", cfg)
    assert cat.display == "gym"
    assert cat.color == auto_color("gym")


def test_config_cannot_shadow_a_builtin(tmp_path):
    (tmp_path / "config.toml").write_text(
        "[[category]]\nslug = 'grocery'\ndisplay = 'HIJACKED'\n"
    )
    cfg = load_config(tmp_path)
    assert get("grocery", cfg).display != "HIJACKED"
    assert len(all_categories(cfg)) == len(BUILTIN)


def test_auto_colour_is_deterministic_and_in_palette():
    assert auto_color("gym") == auto_color("gym")
    assert auto_color("gym") in PALETTE


def test_slugs_works_with_no_config_at_all():
    assert "grocery" in slugs(None)


def test_ui_signal_colors_are_palette_members():
    """The GOOD/BAD/WARN constants in widgets.py and write/view in footer.py
    must stay synchronized with PALETTE. They drifted to literals once; this
    test stops it happening again."""
    from daybook.tui.footer import _KIND_STYLE
    from daybook.tui.widgets import BAD, GOOD, WARN

    assert GOOD in PALETTE, f"GOOD {GOOD} not in PALETTE"
    assert BAD in PALETTE, f"BAD {BAD} not in PALETTE"
    assert WARN in PALETTE, f"WARN {WARN} not in PALETTE"
    assert _KIND_STYLE["write"] in PALETTE, f"write {_KIND_STYLE['write']} not in PALETTE"
    assert _KIND_STYLE["view"] in PALETTE, f"view {_KIND_STYLE['view']} not in PALETTE"
