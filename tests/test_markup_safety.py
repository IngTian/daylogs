"""Stored text is data, not markup.

CLAUDE.md already states the rule twice — "escape anything non-literal before it
reaches markup" and "DataTable cells use rich.Text, not markup" — and both were only
half-applied. A description carrying `[` lost a word from the table, the write toast and
the delete confirmation; a description carrying an unmatched closing tag like `[/b]`
raised `MarkupError` out of the render.

The second one is not a cosmetic bug. `App.on_mount` renders all three tabs, so once such
a row exists the app crashes on *startup* — and the only way back is sqlite3, because the
row cannot be reached to delete it.

`[work]` and `[/b]` are the two shapes that matter: the first is swallowed silently, the
second raises. Both are text a person would type without thinking about it.
"""

from helpers import go_body, go_money
from rich.text import Text

from daylogs.body import add_activity, add_food, add_weight
from daylogs.money import add_expense

# A word in brackets is eaten as a tag; an unmatched closing tag raises. Both are here
# because they fail in different ways and a fix for one need not fix the other.
EATEN = "lunch [work] out"
RAISES = "dinner [/b] out"
DAY = "2026-09-04"


def _cells(app, column: int) -> list[str]:
    """A column's cells as plain text, whatever type the cell is.

    `str()` on a `rich.Text` gives its literal content, which is exactly the point: a
    `Text` cell cannot be re-parsed as markup, so what is stored is what is shown.
    """
    table = app.query_one("#body-table") if app.query("#body-table") else None
    table = table or app.query_one("#money-table")
    return [str(table.get_row_at(r)[column]) for r in range(table.row_count)]


# ── the crash ────────────────────────────────────────────────────────────


async def test_a_food_description_with_a_closing_tag_does_not_crash(make_app, db):
    add_food(db, description=RAISES, kcal=800, source="labeled", date=DAY, at=2)
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        body = app.query_one("#body")
        body.viewing_date = DAY
        body.reload()
        await pilot.pause()
        assert app.is_running, "the render raised out of the app"
        assert RAISES in _cells(app, 1)


async def test_an_expense_description_with_a_closing_tag_does_not_crash(
    make_app, db, make_cfg
):
    cfg = make_cfg()
    add_expense(db, amount=12.4, description=RAISES, category="grocery", date=DAY, cfg=cfg)
    app = make_app(cfg=cfg)
    async with app.run_test(size=(110, 34)) as pilot:
        money = await go_money(pilot, app)
        money.view.pane = "expenses"
        money.reload()
        await pilot.pause()
        assert app.is_running
        cells = [
            str(app.query_one("#money-table").get_row_at(r)[1])
            for r in range(app.query_one("#money-table").row_count)
        ]
        assert RAISES in cells, f"the description is not in the table: {cells}"


async def test_an_activity_description_with_a_closing_tag_does_not_crash(make_app, db):
    add_activity(db, description=RAISES, date=DAY, at=1, factor=1.4, source="estimated")
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        body = app.query_one("#body")
        body.viewing_date = DAY
        body.table_mode = "activity"
        body.reload()
        await pilot.pause()
        assert app.is_running


async def test_a_weight_note_with_a_closing_tag_does_not_crash(make_app, db):
    add_weight(db, kg=80.0, date=DAY, at=1, note=RAISES)
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        body = app.query_one("#body")
        body.viewing_date = DAY
        body.table_mode = "weight"
        body.reload()
        await pilot.pause()
        assert app.is_running


# ── the silent word loss ─────────────────────────────────────────────────


async def test_a_bracketed_word_survives_into_the_table(make_app, db):
    """`[work]` is a tag as far as markup is concerned, so it vanished from the row."""
    add_food(db, description=EATEN, kcal=600, source="labeled", date=DAY, at=1)
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        body = app.query_one("#body")
        body.viewing_date = DAY
        body.reload()
        await pilot.pause()
        cells = _cells(app, 1)
    assert EATEN in cells, f"the bracketed word was eaten: {cells}"


async def test_free_text_cells_are_text_objects_not_markup_strings(make_app, db):
    """The structural half of the rule, and the reason the behavioural tests above pass:
    a `rich.Text` cell is never re-parsed, so no future description can reopen this."""
    add_food(db, description=EATEN, kcal=600, source="labeled", date=DAY, at=1)
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        body = app.query_one("#body")
        body.viewing_date = DAY
        body.reload()
        await pilot.pause()
        table = app.query_one("#body-table")
        description = table.get_row_at(0)[1]
    assert isinstance(description, Text), f"a raw str cell is markup: {description!r}"


async def test_a_bracketed_word_survives_into_the_write_toast(make_app, db, type_into):
    said = []
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        app.notify = lambda msg, **kw: said.append(str(msg))
        await pilot.press("f")
        await type_into(pilot, "lunch \\[work] out =600")
        await pilot.press("enter")
        await pilot.pause()
    assert any("[work]" in m for m in said), f"the toast lost the word: {said}"


async def test_a_bracketed_word_survives_into_the_delete_confirmation(make_app, db):
    """The most dangerous of the three: a confirmation that misquotes the row you are
    about to delete is asking you to approve something other than what it says."""
    add_food(db, description=EATEN, kcal=600, source="labeled", date=DAY, at=1)
    said = []
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        body = app.query_one("#body")
        body.viewing_date = DAY
        body.reload()
        await pilot.pause()
        app.query_one("#body-table").focus()
        app.notify = lambda msg, **kw: said.append(str(msg))
        await pilot.press("x")
        await pilot.pause()
    assert any("[work]" in m for m in said), f"the confirmation misquotes the row: {said}"


async def test_notify_does_not_treat_its_message_as_markup(make_app):
    """Every `notify` call site interpolates stored text somewhere, and none of them
    wants markup. Flipping the default once is what makes that true by construction."""
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.pause()
        app.notify(RAISES)
        await pilot.pause()
        assert app.is_running, "an unmatched tag in a toast raised"


# ── the prompt's own slots ───────────────────────────────────────────────


async def test_a_prompt_error_containing_a_tag_is_shown_literally(make_app, type_into):
    """Error text quotes what you typed — `parse_profile` interpolates the rejected word
    verbatim — so the error slot is a markup sink fed directly by the keyboard."""
    app = make_app()
    async with app.run_test(size=(120, 34)) as pilot:
        await go_body(pilot, app)
        await pilot.press("h")
        await type_into(pilot, "[/b]")
        await pilot.press("enter")
        await pilot.pause()
        assert app.is_running, "a bracketed profile word raised out of the error slot"
        subtitle = str(app.prompt.border_subtitle)
    assert "[/b]" in subtitle, f"the error dropped the word it is quoting: {subtitle!r}"
