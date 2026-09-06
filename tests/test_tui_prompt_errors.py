import datetime as dt

from helpers import all_expenses, assert_armed, go_body, go_money

from daylogs.body import add_food, list_food, list_weight
from daylogs.money import list_recurring, upsert_recurring


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


# ── a rejected submission is still the same submission ──────────────────────
async def test_a_rejected_edit_retries_as_the_same_edit_not_a_new_row(
    make_app, db, type_into
):
    """A retry keeps the text; it has to keep the row too.

    `_take_editing` consumes the armed id on READ, and `_submit_food` raises "kcal is
    required" *after* that read — so the retry found nothing armed, fell into the entry
    branch and INSERTed. One breakfast became two rows and 1,050 kcal, and the ENERGY
    panel's balance for the day was wrong with nothing on screen to explain it.

    `test_a_parse_error_during_edit_keeps_editing_armed` already asserted this property and
    passed throughout, because a bad weight fails inside `parse_weigh` — before the read.
    The bug lives entirely in the errors raised after it.
    """
    at = int(dt.datetime(2026, 8, 28, 7, 5, 43).timestamp())
    add_food(db, description="oatmeal", kcal=350, date="2026-08-28", at=at, source="labeled")
    # Pinned: the food table is span-filtered, so on an unpinned clock the row leaves the
    # window, `enter` arms nothing, and every assertion below passes with the fix out.
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    app = make_app(now=now)
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("enter")
        await pilot.pause()
        assert_armed(app, "body")
        # Drop the `=350` the prefill carried: rejected, with the text kept.
        app.prompt.value = ""
        await type_into(pilot, "oatmeal @2026-08-28")
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open is True, "precondition: rejected, not written"
        assert_armed(app, "body")
        app.prompt.value = ""
        await type_into(pilot, "oatmeal =700 @2026-08-28")
        await pilot.press("enter")
        await pilot.pause()
    rows = list_food(db, date="2026-08-28")
    assert len(rows) == 1, (
        f"the retry inserted a second row: {[(r['description'], r['kcal']) for r in rows]}"
    )
    assert rows[0]["kcal"] == 700, "the retry did not reach the row"
    assert rows[0]["ate_at"] == at, "a line naming no time must not restamp"


async def test_a_rejected_rename_retries_through_the_by_id_edit_path(
    make_app, db, type_into
):
    """The worse half of the same defect: the retry went through `upsert_recurring`.

    That resolves conflicts on `name`, so the retry's new name matched nothing and INSERTed
    a second active row — both then look active and the next `r` writes two budget lines for
    one subscription, which is the whole reason `update_recurring` is keyed by id.
    `_take_editing` had already been spent on the attempt `update_recurring` rejected for
    clashing with `Rent`, so the by-id path was unreachable exactly when the user was
    mid-rename.
    """
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    upsert_recurring(db, name="Rent", category="housing", cost=750, cycle="monthly")
    upsert_recurring(db, name="Gym", category="other", cost=40, cycle="monthly")
    app = make_app(now=now)
    async with app.run_test(size=(120, 34)) as pilot:
        await go_money(pilot, app)
        await pilot.press("tab")
        await pilot.press("tab")            # -> recurring pane
        await pilot.pause()
        # The pane sorts by cost, so Rent (750) is row 0 — step onto Gym, whose rename
        # genuinely collides.
        await pilot.press("down")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert "Gym" in app.prompt.value, "precondition: editing Gym, not Rent"
        assert_armed(app, "money")
        app.prompt.value = ""
        await type_into(pilot, "40 Rent !other #monthly")
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open is True, "precondition: the clash was rejected"
        app.prompt.value = ""
        await type_into(pilot, "40 Gym Membership !other #monthly")
        await pilot.press("enter")
        await pilot.pause()
    names = sorted(r["name"] for r in list_recurring(db))
    assert names == ["Gym Membership", "Rent"], f"the retry INSERTed instead of renaming: {names}"
    assert sum(r["monthly_cost"] for r in list_recurring(db)) == 790.00, (
        "a roll would double-charge"
    )


async def test_escaping_a_rejected_edit_still_disarms_it(make_app, db, type_into):
    """The other half of putting the row back: it must not survive an abandonment.

    An id left armed makes the NEXT plain `s` an update of a row you walked away from — the
    failure `cancel_editing` exists to prevent, already covered for a freshly armed edit.
    This covers the one new way an id can outlive the attempt that read it: the app re-armed
    it after a rejection. The rejected line is a zero cost, which `update_recurring` refuses
    *after* the read, so the slot really is the restored one.
    """
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    upsert_recurring(db, name="Original", cost=20, cycle="monthly", category="subscriptions")
    app = make_app(now=now)
    async with app.run_test(size=(120, 34)) as pilot:
        await go_money(pilot, app)
        await pilot.press("tab")
        await pilot.press("tab")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert_armed(app, "money")
        app.prompt.value = ""
        await type_into(pilot, "0 Original !subscriptions #monthly")
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open is True, "precondition: rejected after the read"
        assert_armed(app, "money")
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("s")
        await type_into(pilot, "9.99 Second !subscriptions #monthly")
        await pilot.press("enter")
        await pilot.pause()
    rows = list_recurring(db)
    assert sorted(r["name"] for r in rows) == ["Original", "Second"], (
        f"the abandoned edit swallowed the next entry: {[(r['name'], r['cost']) for r in rows]}"
    )


# ── the three slots: label above, example inside, grammar below ─────────────


async def test_opening_a_prompt_shows_label_example_and_grammar(make_app):
    """The label used to *be* the placeholder, so it vanished on the first keystroke
    and there was never anywhere to put an example."""
    from daylogs.tui import hints

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
    from daylogs.tui import hints

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
    from daylogs.tui import hints

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
