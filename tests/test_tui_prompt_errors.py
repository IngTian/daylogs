from helpers import all_expenses, go_body

from daybook.body import list_weight


async def test_bad_weight_keeps_the_prompt_open_with_the_text(make_app, db, type_into):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await type_into(pilot, "heavy")
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open is True
        assert app.prompt.value == "heavy"
        assert "weight" in app.prompt.error.lower()
    assert list_weight(db) == []


async def test_the_error_is_visible_while_the_text_is_still_there(make_app, db, type_into):
    """The error must live somewhere that renders when the input is non-empty.

    Textual only draws a placeholder while the value is empty, and the whole
    point of this feature is that the value stays — so a placeholder-only error
    is invisible exactly when it is needed. It goes in the border title.
    """
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await type_into(pilot, "heavy")
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.value == "heavy", "precondition: the text is retained"
        # The subtitle, which the grammar hint otherwise occupies. The title now
        # holds the label, which you still want to see while reading the error.
        assert app.prompt.error in str(app.prompt.border_subtitle)
        assert "weigh" in str(app.prompt.border_title)
        assert app.prompt.has_class("error")


async def test_the_error_does_not_hide_in_the_placeholder(make_app, db, type_into):
    """Regression guard for the original bug."""
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await type_into(pilot, "heavy")
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.error not in app.prompt.placeholder


async def test_the_border_title_clears_on_success(make_app, db, type_into):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await type_into(pilot, "heavy")
        await pilot.press("enter")
        await pilot.pause()
        app.prompt.value = "78.2"
        await pilot.press("enter")
        await pilot.pause()
        assert not app.prompt.border_title


async def test_fixing_the_text_then_submitting_succeeds(make_app, db, type_into):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await type_into(pilot, "heavy")
        await pilot.press("enter")
        await pilot.pause()
        app.prompt.value = "78.2"
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open is False
        assert app.prompt.error == ""
    assert list_weight(db)[0]["kg"] == 78.2


async def test_escape_abandons_a_failed_entry(make_app, db, type_into):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await type_into(pilot, "heavy")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.prompt.is_open is False
        assert app.prompt.error == ""
    assert list_weight(db) == []


async def test_bad_expense_keeps_its_text_too(make_app, db, type_into):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        await pilot.press("e")
        await type_into(pilot, "lunch")
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open is True
        assert app.prompt.value == "lunch"
    assert all_expenses(db) == []


async def test_an_unknown_category_keeps_its_text(make_app, db, type_into):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        await pilot.press("b")
        await type_into(pilot, "500 nonsense")
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open is True
        assert "nonsense" in app.prompt.value


async def test_a_successful_entry_is_remembered_in_history(make_app, db, type_into):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await type_into(pilot, "78.2")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("w")
        await pilot.press("up")
        assert app.prompt.value == "78.2"


async def test_a_rejected_entry_is_not_remembered(make_app, db, type_into):
    """History is for things that worked; recalling a rejected line is noise."""
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await type_into(pilot, "heavy")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("w")
        await pilot.press("up")
        assert app.prompt.value == ""


async def test_a_handler_that_chains_to_another_prompt_is_not_stomped(make_app, db, type_into):
    """An uncategorised expense writes the row and re-opens as `fix category`.
    The app closes the prompt after a successful handler, so it must not close a
    *different* prompt the handler just opened."""
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        await pilot.press("e")
        await type_into(pilot, "12.40 lunch")
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open is True
        assert app.prompt.label == "fix category"


# ── the three slots: label above, example inside, grammar below ─────────────


async def test_opening_a_prompt_shows_label_example_and_grammar(make_app):
    """The label used to *be* the placeholder, so it vanished on the first keystroke
    and there was never anywhere to put an example."""
    from daybook.tui import hints

    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("h")
        await pilot.pause()
        title = str(app.prompt.border_title)
        placeholder = app.prompt.placeholder
        subtitle = str(app.prompt.border_subtitle)
    hint = hints.for_label("profile")
    assert "profile" in title
    assert placeholder == hint.example
    assert subtitle == hint.grammar


async def test_the_grammar_survives_typing_but_the_example_does_not(make_app, type_into):
    """The example is scaffolding and should get out of the way; the grammar is what
    you still want halfway through a line."""
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await pilot.pause()
        before = str(app.prompt.border_subtitle)
        await type_into(pilot, "78")
        await pilot.pause()
        after = str(app.prompt.border_subtitle)
        value = app.prompt.value
    assert value == "78"
    assert after == before
    assert after


async def test_each_prompt_shows_its_own_grammar_not_the_previous_one(make_app):
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await pilot.pause()
        weigh = str(app.prompt.border_subtitle)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("h")
        await pilot.pause()
        profile = str(app.prompt.border_subtitle)
    assert weigh != profile
    assert "kg" in weigh
    assert "height" in profile


async def test_closing_the_prompt_clears_every_slot(make_app, db, type_into):
    """A hidden widget holding a stale label and grammar is the same class of bug as
    the burn bar that kept the previous month's numbers."""
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await type_into(pilot, "78.2")
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open is False
        title = str(app.prompt.border_title)
        subtitle = str(app.prompt.border_subtitle)
        placeholder = app.prompt.placeholder
    assert not title
    assert not subtitle
    assert not placeholder


async def test_fixing_an_error_restores_the_grammar(make_app, db, type_into):
    from daybook.tui import hints

    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await type_into(pilot, "heavy")
        await pilot.press("enter")
        await pilot.pause()
        errored = str(app.prompt.border_subtitle)
        app.prompt.value = ""
        await type_into(pilot, "78.2")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("w")
        await pilot.pause()
        restored = str(app.prompt.border_subtitle)
    assert "weight" in errored
    assert restored == hints.for_label("weigh").grammar


# ── completion ──────────────────────────────────────────────────────────────


async def test_tab_completes_a_category(make_app, type_into):
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("3")
        await pilot.press("e")
        await type_into(pilot, "12.40 lunch !gro")
        await pilot.press("tab")
        await pilot.pause()
        value = app.prompt.value
    assert value == "12.40 lunch !grocery "


async def test_tab_still_changes_sub_view_when_the_prompt_is_closed(make_app):
    """The binding has to keep its original job."""
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        before = app.query_one("#money").view.pane
        await pilot.press("tab")
        await pilot.pause()
        after = app.query_one("#money").view.pane
    assert before != after


async def test_the_border_shows_candidates_while_in_a_sigil_token(make_app, type_into):
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("3")
        await pilot.press("e")
        await type_into(pilot, "12.40 lunch !")
        await pilot.pause()
        subtitle = str(app.prompt.border_subtitle)
    assert "grocery" in subtitle
    assert "restaurant" in subtitle


async def test_the_border_returns_to_the_grammar_outside_a_sigil_token(make_app, type_into):
    from daybook.tui import hints

    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("3")
        await pilot.press("e")
        await type_into(pilot, "12.40 lunch !grocery")
        await pilot.press("tab")
        await pilot.pause()
        subtitle = str(app.prompt.border_subtitle)
    assert subtitle == hints.for_label("expense").grammar


async def test_repeated_tabs_cycle_an_ambiguous_prefix(make_app, type_into):
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("3")
        await pilot.press("e")
        await type_into(pilot, "12.40 x !e")
        await pilot.press("tab")
        await pilot.pause()
        first = app.prompt.value
        await pilot.press("tab")
        await pilot.pause()
        second = app.prompt.value
    assert first != second
    assert {first.strip().split("!")[-1], second.strip().split("!")[-1]} == {
        "education",
        "entertainment",
    }


async def test_tab_in_a_prompt_with_no_vocabulary_does_nothing(make_app, type_into):
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await type_into(pilot, "78.2 post")
        await pilot.press("tab")
        await pilot.pause()
        value = app.prompt.value
    assert value == "78.2 post"


async def test_completing_mid_line_leaves_the_cursor_after_the_completed_word(make_app, type_into):
    """The pure engine is tested for this; this proves the widget does not clamp it."""
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("3")
        await pilot.press("e")
        await type_into(pilot, "12.40 lunch !gro")
        await type_into(pilot, " extra")
        # cursor is at the end; walk it back into the sigil token
        app.prompt.cursor_position = len("12.40 lunch !gro")
        await pilot.press("tab")
        await pilot.pause()
        value, cursor = app.prompt.value, app.prompt.cursor_position
    assert value == "12.40 lunch !grocery extra"
    assert cursor == len("12.40 lunch !grocery")
