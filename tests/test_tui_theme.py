"""Choosing a theme: `T`, a live preview you arrow through, and a line in config.toml.

The theme itself is Textual's — see test_themes.py. What is ours is the wiring: read it
at startup, let `T` change it, write it back, and never let a cosmetic setting stop the
app.

`T` used to open a text prompt with tab completion, and the reason recorded at the time
was that "cycling 21 themes one keypress at a time would take up to 21 presses to get
back to one you liked". That answered the wrong question. It assumed you already know
which name you want, and the difficulty with a theme is that the name tells you nothing —
you have to see it against the charts, the bars and the good/bad colours, which are
deliberately not themed. The picker previews, and `esc` answers the original objection in
one keypress instead of twenty-one.
"""

from helpers import go_body, go_money

from daylogs.tui import themes
from daylogs.tui.themes import ThemePicker


def _picker(app) -> ThemePicker:
    return app.query_one(ThemePicker)


def _shown(app) -> str:
    p = _picker(app)
    return str(p.render()) if p.display else ""


# ── startup ──────────────────────────────────────────────────────────────
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


async def test_the_picker_is_hidden_until_asked_for(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert _picker(app).display is False


# ── opening ──────────────────────────────────────────────────────────────
async def test_T_opens_the_picker_on_the_current_theme(make_app, make_cfg):
    app = make_app(cfg=make_cfg(theme="nord"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("T")
        await pilot.pause()
        assert _picker(app).is_open is True
        assert _picker(app).selected == "nord", "the picker should start where you are"


async def test_it_opens_on_what_is_on_screen_not_on_what_config_says(make_app, make_cfg):
    """The two differ exactly when config.toml names a theme Textual does not have: the
    app fell back at startup, so opening on `cfg.theme` would land on whatever happens to
    sort first and the first `→` would jump somewhere unrelated."""
    app = make_app(cfg=make_cfg(theme="theme-that-was-removed"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("T")
        await pilot.pause()
        assert _picker(app).selected == themes.DEFAULT


async def test_the_picker_shows_the_options_and_where_you_are_in_them(make_app, make_cfg):
    app = make_app(cfg=make_cfg(theme="nord"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("T")
        await pilot.pause()
        body, title, sub = (
            _shown(app),
            str(_picker(app).border_title),
            str(_picker(app).border_subtitle),
        )
    assert "nord" in body, f"the selected name is not in the strip: {body!r}"
    assert "▸nord◂" in body, "the cursor has to be marked by characters, not by colour"
    after = themes.names()[themes.names().index("nord") + 1]
    assert "monokai" in body, f"nothing to the left of the cursor: {body!r}"
    assert after in body, f"nothing to the right of the cursor: {body!r}"
    assert f"of {len(themes.names())}" in title, f"no position in the list: {title!r}"
    # The one thing you cannot see once every colour on screen has changed.
    assert "restores nord" in sub, f"esc's target is not named: {sub!r}"


# ── previewing ───────────────────────────────────────────────────────────
async def test_right_applies_the_next_theme_immediately(make_app, make_cfg):
    """The whole point: the app you are looking at *is* the preview."""
    app = make_app(cfg=make_cfg(theme="nord"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("T")
        await pilot.press("right")
        await pilot.pause()
        after = themes.names()[themes.names().index("nord") + 1]
        assert app.theme == after, f"the theme did not follow the cursor: {app.theme}"
        assert _picker(app).selected == after


async def test_left_goes_back(make_app, make_cfg):
    app = make_app(cfg=make_cfg(theme="nord"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("T")
        await pilot.press("right")
        await pilot.press("right")
        await pilot.press("left")
        await pilot.pause()
        assert app.theme == themes.names()[themes.names().index("nord") + 1]


async def test_the_ends_wrap(make_app, make_cfg):
    """Wrapping is what bounds the walk at half the list rather than all of it."""
    names = themes.names()
    app = make_app(cfg=make_cfg(theme=names[0]))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("T")
        await pilot.press("left")
        await pilot.pause()
        assert app.theme == names[-1], "the first theme's left neighbour is the last"
        await pilot.press("right")
        await pilot.pause()
        assert app.theme == names[0]


async def test_previewing_writes_nothing(make_app, make_cfg):
    """Twenty presses is twenty rewrites of config.toml, and the last one would be
    whichever theme you happened to be passing through when you gave up."""
    cfg = make_cfg(theme="nord")
    app = make_app(cfg=cfg)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("T")
        for _ in range(3):
            await pilot.press("right")
        await pilot.pause()
    written = cfg.root / "config.toml"
    assert not written.exists() or "theme" not in written.read_text()


async def test_the_arrows_do_not_walk_the_tabs_while_previewing(make_app, make_cfg):
    """The collision this design had to solve. `←`/`→` are app-scope tab navigation and
    deliberately *not* priority bindings, which is what lets a focused widget's `on_key`
    claim them first — the same route `InlinePrompt` takes for `escape`."""
    app = make_app(cfg=make_cfg(theme="nord"))
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("T")
        await pilot.press("right")
        await pilot.press("right")
        await pilot.pause()
        assert app.scope == "body", f"the arrows switched tabs instead of themes: {app.scope}"


async def test_tabs_are_still_reachable_by_digit_while_previewing(make_app, make_cfg):
    """The charts are on Body and the summary is on Day, so being pinned to one tab would
    hide most of what you are trying to look at. Focus has to come back to the picker, or
    the arrows resume walking tabs halfway through."""
    app = make_app(cfg=make_cfg(theme="nord"))
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("T")
        await pilot.press("3")
        await pilot.pause()
        assert app.scope == "money"
        assert _picker(app).is_open is True, "switching tabs closed the picker"
        before = app.theme
        await pilot.press("right")
        await pilot.pause()
        assert app.theme != before, "the arrows stopped previewing after a tab switch"
        assert app.scope == "money", "the arrow walked a tab instead"


# ── keeping and cancelling ───────────────────────────────────────────────
async def test_enter_keeps_it_and_writes_it_to_config(make_app, make_cfg):
    cfg = make_cfg(theme="nord")
    app = make_app(cfg=cfg)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("T")
        await pilot.press("right")
        chosen = _picker(app).selected
        await pilot.press("enter")
        await pilot.pause()
        assert app.theme == chosen
        assert _picker(app).is_open is False
    written = (cfg.root / "config.toml").read_text()
    assert f'theme = "{chosen}"' in written, f"not persisted: {written!r}"


async def test_enter_gives_focus_back_to_the_tab(make_app, make_cfg):
    """Otherwise the picker keeps the keyboard and the next `x` or `enter` goes nowhere."""
    app = make_app(cfg=make_cfg(theme="nord"))
    async with app.run_test(size=(120, 30)) as pilot:
        money_tab = await go_money(pilot, app)
        await pilot.press("T")
        await pilot.press("enter")
        await pilot.pause()
        # Not `is not _picker(app)`: hiding a widget drops its focus on its own, so that
        # assertion passes even when focus is handed back to nobody and the next keypress
        # goes to the screen.
        assert app.focused is money_tab.query_one("#money-table"), app.focused


async def test_esc_restores_what_you_started_with_in_one_keypress(make_app, make_cfg):
    """The answer to the objection the typed prompt was built around: getting back to the
    theme you liked costs one key, not up to twenty-one."""
    cfg = make_cfg(theme="nord")
    app = make_app(cfg=cfg)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("T")
        for _ in range(6):
            await pilot.press("right")
        await pilot.pause()
        assert app.theme != "nord", "this test would prove nothing without a change first"
        await pilot.press("escape")
        await pilot.pause()
        assert app.theme == "nord", "esc did not put the original back"
        assert _picker(app).is_open is False
    written = cfg.root / "config.toml"
    assert not written.exists() or 'theme = "nord"' not in written.read_text(), (
        "a cancelled preview wrote to config.toml"
    )


async def test_esc_gives_focus_back_to_the_tab(make_app, make_cfg):
    app = make_app(cfg=make_cfg(theme="nord"))
    async with app.run_test(size=(120, 30)) as pilot:
        await go_money(pilot, app)
        await pilot.press("T")
        await pilot.press("escape")
        await pilot.pause()
        assert app.focused is app.query_one("#money").query_one("#money-table"), app.focused


async def test_reopening_after_a_cancel_starts_where_you_are_again(make_app, make_cfg):
    app = make_app(cfg=make_cfg(theme="nord"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("T")
        await pilot.press("right")
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("T")
        await pilot.pause()
        assert _picker(app).selected == "nord"
