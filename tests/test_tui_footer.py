from helpers import go_day
from textual.content import Content

from daybook.tui import keymap as km
from daybook.tui.footer import glyph, render_keys


def plain(markup: str) -> str:
    """The footer is colour-coded, so its return value carries markup. Width
    guarantees are about rendered columns, not string length."""
    return Content.from_markup(markup).plain


def test_footer_shows_the_active_tabs_own_verbs_first():
    text = render_keys("body", width=300)
    assert text.index("weigh") < text.index("today")


def test_footer_never_names_a_key_that_is_not_in_the_map():
    """The whole reason the footer is generated: a hand-written one can describe
    a key that isn't bound."""
    for scope in ("body", "money", "summary"):
        text = render_keys(scope, width=300)
        labels = {k.label for k in km.footer_keys(scope)}
        for word in ("weigh", "expense", "regenerate", "budget", "photo"):
            if word in text:
                assert word in labels, f"{word!r} shown for {scope!r} but not bound"


def test_money_footer_has_money_verbs_and_not_body_verbs():
    text = render_keys("money", width=300)
    assert "expense" in text and "budget" in text
    assert "weigh" not in text


def test_body_footer_has_body_verbs_and_not_money_verbs():
    text = render_keys("body", width=300)
    assert "weigh" in text and "photo" in text
    assert "expense" not in text


def test_summary_footer_has_regenerate():
    assert "regenerate" in render_keys("summary", width=300)


def test_footer_includes_app_keys():
    text = render_keys("money", width=300)
    assert "today" in text and "quit" in text


def test_narrow_footer_truncates_rather_than_wrapping():
    narrow = render_keys("money", width=40)
    assert len(plain(narrow)) <= 40
    assert "\n" not in narrow


def test_narrow_footer_keeps_the_tabs_first_verb():
    narrow = render_keys("money", width=40)
    assert "expense" in narrow


def test_absurdly_narrow_footer_returns_empty_not_a_crash():
    assert render_keys("money", width=2) == ""


def test_glyphs_are_human_readable_not_textual_names():
    assert glyph("left_square_bracket") == "["
    assert glyph("question_mark") == "?"
    assert glyph("slash") == "/"
    assert glyph("escape") == "esc"
    assert glyph("w") == "w"


def test_footer_never_shows_a_raw_textual_key_name():
    for scope in km.SCOPES:
        text = render_keys(scope, width=400)
        for ugly in ("left_square_bracket", "question_mark", "right_curly_bracket"):
            assert ugly not in text


# ── live ─────────────────────────────────────────────────────────────────
async def test_footer_updates_when_the_tab_changes(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "regenerate" in str(app.query_one("#keyfooter").content)
        await pilot.press("2")
        await pilot.pause()
        assert "weigh" in str(app.query_one("#keyfooter").content)
        await pilot.press("3")
        await pilot.pause()
        assert "expense" in str(app.query_one("#keyfooter").content)


async def test_footer_shows_the_tabs_state_chip(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        text = str(app.query_one("#keyfooter").content)
    assert "2026" in text or "august" in text.lower()


async def test_question_mark_opens_the_help_overlay(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        assert any(s.__class__.__name__ == "HelpScreen" for s in app.screen_stack)


async def test_escape_closes_the_help_overlay(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("question_mark")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not any(s.__class__.__name__ == "HelpScreen" for s in app.screen_stack)


async def test_question_mark_also_closes_the_overlay(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("question_mark")
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        assert not any(s.__class__.__name__ == "HelpScreen" for s in app.screen_stack)


async def test_help_lists_every_key_in_the_map(make_app):
    """Generated from KEYMAP, so a bound key can never be undocumented."""
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("question_mark")
        await pilot.pause()
        text = "\n".join(str(w.content) for w in app.screen.query("Static"))
    for k in km.KEYMAP:
        assert k.label in text, f"{k.label!r} missing from the help overlay"


async def test_help_groups_keys_under_headings(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("question_mark")
        await pilot.pause()
        text = "\n".join(str(w.content) for w in app.screen.query("Static"))
    for heading in ("Move around", "Change the view", "Record something"):
        assert heading in text


async def test_help_marks_which_tab_a_scoped_key_belongs_to(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("question_mark")
        await pilot.pause()
        text = "\n".join(str(w.content) for w in app.screen.query("Static"))
    assert "(Body)" in text and "(Money)" in text and "(Summary)" in text


def test_pinned_keys_survive_a_narrow_footer():
    """`?` is how you discover everything and `q` is how you leave. They sit last,
    so naive right-truncation drops them first — exactly backwards."""
    for width in (200, 80, 40, 24):
        text = render_keys("money", width=width)
        assert "keys" in text, f"? dropped at width {width}: {text!r}"
        assert "quit" in text, f"q dropped at width {width}: {text!r}"


def test_pinned_keys_come_last_when_everything_fits():
    text = plain(render_keys("body", width=400))
    assert text.rstrip().endswith("q quit")


def test_droppable_keys_are_shed_before_pinned_ones():
    wide = render_keys("money", width=300)
    narrow = render_keys("money", width=50)
    assert len(narrow) < len(wide)
    assert "keys" in narrow and "quit" in narrow


async def test_footer_adapts_when_the_terminal_resizes(make_app):
    """The footer sheds keys to fit, so it must recompute on resize — otherwise
    it keeps whatever it guessed before the first layout."""
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        wide = str(app.query_one("#keyfooter").content)
        await pilot.resize_terminal(56, 40)
        await pilot.pause()
        narrow = str(app.query_one("#keyfooter").content)
    assert len(narrow) < len(wide), f"footer did not shrink: {narrow!r}"
    assert "quit" in narrow and "keys" in narrow


async def test_footer_uses_the_real_width_at_mount(make_app):
    """self.size is 0 during on_mount; falling back to a narrow guess silently
    drops keys that would have fitted."""
    app = make_app()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        text = str(app.query_one("#keyfooter").content)
    assert "today" in text, f"a wide terminal should show `t today`: {text!r}"


# ── two rows, grouped ───────────────────────────────────────────────────────


def test_the_bracket_key_is_escaped_not_swallowed_as_markup():
    """`[` is itself a key. Unescaped it opens a colour tag, and the hint rendered
    as "[[/] prev" — the one hint guaranteed to break. `rich.markup.escape` does
    not help: it leaves a bare `[` alone."""
    text = plain(render_keys("body", width=400))
    assert "[ prev" in text
    assert "[/]" not in text
    assert "[[" not in text


def test_groups_are_separated_more_widely_than_keys_within_a_group():
    """Three groups means two wide breaks — that visual grouping is the whole
    point of the change, so assert the structure rather than a specific key."""
    text = plain(render_keys("money", width=400))
    assert " · " in text
    assert text.count("   ") == 2


def test_actions_come_before_view_controls_before_navigation():
    text = plain(render_keys("money", width=400))
    assert text.index("expense") < text.index("by cost") < text.index("today")


def test_delete_and_undo_sit_with_the_action_verbs_not_after_quit():
    text = plain(render_keys("body", width=400))
    assert text.index("delete") < text.index("quit")
    assert text.index("undo") < text.index("quit")


def test_keys_are_colour_coded_by_kind():
    from daybook.tui.footer import _KIND_STYLE

    text = render_keys("money", width=400)
    assert _KIND_STYLE["write"] in text
    assert _KIND_STYLE["view"] in text


def test_plain_width_is_respected_at_every_width():
    """The fit check measures plain text; measuring the styled string would be
    wrong by the length of its colour codes."""
    for width in (400, 200, 120, 80, 60, 40, 30):
        assert len(plain(render_keys("money", width=width))) <= width


async def test_footer_occupies_two_rows(make_app):
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        footer = app.query_one("#keyfooter")
        content = str(footer.content)
        height = footer.size.height
    assert height == 2
    assert content.count("\n") == 1


async def test_state_row_and_key_row_are_separate_lines(make_app):
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        state, keys = str(app.query_one("#keyfooter").content).split("\n")
    assert "sort" in state
    assert "expense" in keys
    assert "sort" not in keys


async def test_money_state_row_shows_all_sort_fields_with_the_active_one_marked(make_app):
    """Naming only the current sort hides what else is available; showing the whole
    set with the active one emphasised does not."""
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        state = plain(str(app.query_one("#keyfooter").content).split("\n")[0])
    for field in ("date", "cost", "category"):
        assert field in state
    assert "↓date" in state


async def test_money_state_row_follows_a_sort_change(make_app):
    app = make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("3")
        await pilot.press("c")
        await pilot.pause()
        state = plain(str(app.query_one("#keyfooter").content).split("\n")[0])
    assert "↓cost" in state
    assert "↓date" not in state


async def test_the_footer_never_advertises_a_key_nothing_handles(make_app):
    """`tab` and `+` are app-scope, but Summary implements neither sub-views nor
    horizons — both were drawn and both were dead on press. A generated footer that
    names dead keys has the same defect as a hand-written one."""
    app = make_app()
    async with app.run_test(size=(160, 30)) as pilot:
        await go_day(pilot, app)      # say which tab, don't lean on where it opens
        keys = plain(str(app.query_one("#keyfooter").content).split("\n")[1])
    assert "regenerate" in keys
    assert "next view" not in keys
    assert "wider" not in keys


async def test_the_footer_still_advertises_keys_the_tab_does_handle(make_app):
    app = make_app()
    async with app.run_test(size=(160, 30)) as pilot:
        await go_day(pilot, app)      # say which tab, don't lean on where it opens
        keys = plain(str(app.query_one("#keyfooter").content).split("\n")[1])
    for expected in ("prev", "next", "today", "quit", "keys"):
        assert expected in keys, f"{expected!r} missing from the Summary footer"


async def test_body_and_money_keep_their_sub_view_and_horizon_keys(make_app):
    app = make_app()
    async with app.run_test(size=(200, 30)) as pilot:
        for key in ("2", "3"):
            await pilot.press(key)
            await pilot.pause()
            keys = plain(str(app.query_one("#keyfooter").content).split("\n")[1])
            assert "next view" in keys
            assert "wider" in keys
