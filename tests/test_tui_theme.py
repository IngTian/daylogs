"""Choosing a theme: `T`, a prompt, and a line in config.toml.

The theme itself is Textual's — see test_themes.py. What is ours is the wiring:
read it at startup, let `T` change it, write it back, and never let a cosmetic
setting stop the app.
"""

from daylogs.tui import themes


async def test_the_app_starts_on_the_configured_theme(make_app, make_cfg):
    app = make_app(cfg=make_cfg(theme="nord"))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.theme == "nord"


async def test_the_default_is_gruvbox_when_config_says_nothing(make_app, make_cfg):
    """PALETTE was tuned for a dark warm-earth background, which is what gruvbox
    is, so the nine category hues sit in harmony with it."""
    app = make_app(cfg=make_cfg())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.theme == "gruvbox"


async def test_an_unknown_theme_in_config_falls_back_instead_of_crashing(make_app, make_cfg):
    """config.toml is hand-edited and theme names belong to a dependency, so a
    stale one is expected. Refusing to start over it would be a cosmetic setting
    taking down the whole app."""
    app = make_app(cfg=make_cfg(theme="theme-that-was-removed"))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.theme == themes.DEFAULT
        assert app.is_running is True


async def test_T_opens_the_theme_prompt(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("T")
        await pilot.pause()
        assert app.prompt.is_open is True
        assert app.prompt.label == "theme"


async def test_submitting_a_theme_applies_it_and_writes_it_to_config(
    make_app, make_cfg, type_into
):
    cfg = make_cfg()
    app = make_app(cfg=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("T")
        await type_into(pilot, "nord")
        await pilot.press("enter")
        await pilot.pause()
        assert app.theme == "nord", "the theme did not change"
        assert app.prompt.is_open is False
    written = (cfg.root / "config.toml").read_text()
    assert 'theme = "nord"' in written, f"not persisted: {written!r}"


async def test_an_unknown_typed_theme_keeps_the_prompt_open_with_an_error(
    make_app, make_cfg, type_into
):
    """Silently substituting a theme after someone typed one would read as a
    swallowed keypress — so the typed path objects where the config path falls back.
    """
    cfg = make_cfg()
    app = make_app(cfg=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("T")
        await type_into(pilot, "gruvbax")
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open is True, "a rejected theme must keep your text"
        assert app.prompt.error
        assert app.theme == themes.DEFAULT, "a rejected theme must not be applied"
    written = cfg.root / "config.toml"
    if written.exists():
        assert "gruvbax" not in written.read_text(), "a rejected theme must not persist"


async def test_tab_completes_a_theme_name(make_app, type_into):
    """Cycling 21 themes one keypress at a time would take up to 21 presses to get
    back to one you liked, so this prompt completes instead."""
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("T")
        await type_into(pilot, "tokyo")
        await pilot.press("tab")
        await pilot.pause()
        value = app.prompt.value
    assert value.strip() == "tokyo-night", f"tab did not complete the theme: {value!r}"
