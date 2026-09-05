"""Pausing a recurring item — the half-feature that shipped with no way to reach it.

`recurring.active` has been in the schema since the first version. `roll_month_budgets`
and `pending_roll` both filter on it, `update_recurring` has always accepted it, and the
pane renders an `on` column from it. Nothing could ever set it, so the column read `yes`
for every row forever and the filtering was dead weight.

Which made it the one place the repo broke its own rule — *what you can see is what you
can edit* — and in the direction the rule forbids: a column on screen that nothing could
change. `o` is that missing keypress. It stays a key rather than becoming a token in the
recurring grammar because a boolean's entire edit is a toggle; in the line, every
recurring item would carry a field that reads "on" almost always.
"""

import datetime as dt

from helpers import go_money

from daylogs.money import (
    add_expense,
    list_budget,
    list_recurring,
    pending_roll,
    upsert_recurring,
)

NOW = dt.datetime(2026, 8, 28, 9, 0)


def _seed(db, *, name="Streaming", cost=20.99, cycle="monthly", category="subscriptions"):
    return upsert_recurring(db, name=name, cost=cost, cycle=cycle, category=category)


def _one(db):
    return list_recurring(db)[0]


async def _on_recurring(pilot, app):
    """The recurring pane with the cursor on its first row."""
    money_tab = await go_money(pilot, app)
    money_tab.view.pane = "recurring"
    money_tab.reload()
    await pilot.pause()
    return money_tab


# ── the toggle ───────────────────────────────────────────────────────────
async def test_o_pauses_the_selected_item(make_app, db):
    _seed(db)
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        await _on_recurring(pilot, app)
        await pilot.press("o")
        await pilot.pause()
    assert _one(db)["active"] == 0


async def test_o_again_brings_it_back(make_app, db):
    """A toggle, not a one-way pause: the flag is read from the row rather than set to a
    constant, so the key is the whole interface to both directions."""
    _seed(db)
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        await _on_recurring(pilot, app)
        await pilot.press("o")
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()
    assert _one(db)["active"] == 1


async def test_the_on_column_follows_the_flag(make_app, db):
    """The column existed and always read `yes`. It is the only thing on screen that says
    an item is paused, so it has to move on the keystroke."""
    _seed(db)
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        await _on_recurring(pilot, app)
        table = app.query_one("#money-table")
        assert [str(c) for c in table.get_row_at(0)][-1] == "yes"
        await pilot.press("o")
        await pilot.pause()
        assert [str(c) for c in app.query_one("#money-table").get_row_at(0)][-1] == "no"


async def test_pausing_says_what_it_changes(make_app, db):
    """The pane shows no total, so the column flipping is a small signal for a change
    that silently alters what `r` will do next month. The toast names the item, the new
    state and the key that undoes it."""
    said = []
    _seed(db)
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        await _on_recurring(pilot, app)
        app.notify = lambda msg, **kw: said.append(str(msg))
        await pilot.press("o")
        await pilot.pause()
    assert said, "pausing an item said nothing"
    assert "Streaming" in said[0]
    assert "paused" in said[0], said[0]
    # Whole phrases, not `"r" in said[0]`: a single character matches the item's own name
    # ("Streaming" contains an r, "paused" contains a u), so both of those assertions were
    # vacuous and two mutations walked straight through them.
    assert "r will skip it" in said[0], f"the toast must name what stops happening: {said[0]}"
    assert "u to undo" in said[0], f"the toast must name undo: {said[0]}"


async def test_resuming_says_the_opposite(make_app, db):
    """The toast is generated from the flag, so the direction has to be right in both
    directions — "r will skip it" on a resume would be exactly backwards."""
    said = []
    _seed(db)
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        await _on_recurring(pilot, app)
        await pilot.press("o")
        await pilot.pause()
        said.clear()
        app.notify = lambda msg, **kw: said.append(str(msg))
        await pilot.press("o")
        await pilot.pause()
    assert "resumed" in said[0], said[0]
    assert "r will roll it again" in said[0], said[0]


async def test_a_row_that_vanished_between_reload_and_keypress_is_not_a_crash(make_app, db):
    """The same guard `_submit_recurring` carries, and reachable the same way: the pane's
    id list is built at reload, so anything that removes the row without one leaves a
    stale id behind. Called directly because there is no keystroke that deletes a row
    without reloading — which is exactly why the guard is defensive and needs a test."""
    _seed(db)
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        money_tab = await _on_recurring(pilot, app)
        db.execute("DELETE FROM recurring")
        money_tab.key_toggle_active()
        await pilot.pause()
        assert app.is_running is True
    assert list_recurring(db) == []


async def test_u_restores_the_flag(make_app, db):
    """Undo is an upsert on the primary key, so an edit's pre-image restores in one
    statement. A toggle is an edit like any other and must ride the same stack."""
    _seed(db)
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        await _on_recurring(pilot, app)
        await pilot.press("o")
        await pilot.pause()
        assert _one(db)["active"] == 0
        await pilot.press("u")
        await pilot.pause()
    assert _one(db)["active"] == 1


async def test_the_toggle_disturbs_nothing_else(make_app, db):
    """`update_recurring` recomputes `monthly_cost` whenever cost or cycle moves, and the
    toggle passes neither — so the derived column must sit still."""
    _seed(db, cost=240.0, cycle="annually")
    before = dict(_one(db))
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        await _on_recurring(pilot, app)
        await pilot.press("o")
        await pilot.pause()
    after = dict(_one(db))
    assert {k: v for k, v in after.items() if k != "active"} == {
        k: v for k, v in before.items() if k != "active"
    }
    assert after["monthly_cost"] == 20.0


# ── what pausing is for ──────────────────────────────────────────────────
async def test_a_paused_item_is_not_rolled(make_app, db):
    """The point of the whole feature. `roll_month_budgets` already filtered on `active`;
    until now nothing could put an item on the other side of that filter."""
    _seed(db)
    _seed(db, name="Gym", cost=50.0, category="entertainment")
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        money_tab = await _on_recurring(pilot, app)
        paused = _one(db)["name"]     # monthly_cost DESC — the cursor opens on Gym
        assert paused == "Gym"
        await pilot.press("o")
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        month = money_tab._budget_month()
    names = {r["name"] for r in list_budget(db, month=month)}
    assert paused not in names, f"a paused item was rolled anyway: {names}"
    assert len(names) == 1


async def test_the_empty_state_stops_counting_a_paused_item(make_app, db):
    """`money.pending_roll` must agree with `roll_month_budgets` or the header promises
    what `r` will not deliver — which is the same invariant, now reachable from a key."""
    _seed(db)
    _seed(db, name="Gym", cost=50.0, category="entertainment")
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        await _on_recurring(pilot, app)
        # `list_recurring` orders by monthly_cost DESC, so the cursor opens on Gym.
        assert _one(db)["name"] == "Gym"
        await pilot.press("o")
        await pilot.pause()
    assert pending_roll(db, month="2026-08") == (1, 20.99), "Streaming alone is left"


async def test_pausing_leaves_a_line_already_rolled_alone(make_app, db):
    """A month you have already paid for keeps its budget. Pausing says "not from now
    on", not "this never happened" — the same stance `_rename_rolled_budgets` takes on a
    deleted item's line, and the reason there is no un-roll."""
    _seed(db)
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        await _on_recurring(pilot, app)
        await pilot.press("r")
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()
    assert [r["name"] for r in list_budget(db, month="2026-08")] == ["Streaming"]


async def test_re_adding_by_name_does_not_quietly_un_pause(make_app, db, type_into):
    """`s` is add-*or-update*, resolved on name, and its ON CONFLICT clause used to set
    `active = excluded.active` — so raising a paused subscription's price un-paused it,
    and the next roll charged you for it with nothing on screen connecting the two.

    Pausing is a state you set deliberately; a re-add is about cost, cycle and category.
    """
    _seed(db)
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        await _on_recurring(pilot, app)
        await pilot.press("o")
        await pilot.pause()
        await pilot.press("s")
        await type_into(pilot, "24.99 Streaming !subscriptions #monthly")
        await pilot.press("enter")
        await pilot.pause()
    row = _one(db)
    assert row["cost"] == 24.99, "the re-add did not take"
    assert row["active"] == 0, "re-adding by name un-paused a paused item"


# ── where it does and does not apply ─────────────────────────────────────
async def test_o_on_the_categories_pane_explains_itself(make_app, db):
    """The same shape as `x`: a category is not a row you can pause, and silence would
    read as a dropped keypress."""
    said = []
    _seed(db)
    add_expense(db, amount=12.0, description="milk", category="grocery", date="2026-08-04")
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        money_tab = await go_money(pilot, app)
        assert money_tab.view.pane == "categories"
        app.notify = lambda msg, **kw: said.append(str(msg))
        await pilot.press("o")
        await pilot.pause()
    assert said and "recurring" in said[0], said
    assert _one(db)["active"] == 1


async def test_o_on_the_expenses_pane_explains_itself(make_app, db):
    """An expense is a thing that happened once; there is nothing to switch off."""
    said = []
    _seed(db)
    add_expense(db, amount=12.0, description="milk", category="grocery", date="2026-08-04")
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        money_tab = await go_money(pilot, app)
        money_tab.view.pane = "expenses"
        money_tab.reload()
        await pilot.pause()
        app.notify = lambda msg, **kw: said.append(str(msg))
        await pilot.press("o")
        await pilot.pause()
    assert said and "recurring" in said[0], said
    assert _one(db)["active"] == 1


async def test_o_with_no_rows_at_all_does_not_raise(make_app, db):
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        await _on_recurring(pilot, app)
        await pilot.press("o")
        await pilot.pause()
        assert app.is_running is True


# ── the cursor, and the empty pane ───────────────────────────────────────
async def test_a_second_o_undoes_the_first_rather_than_pausing_another_row(make_app, db):
    """`o` is the only write key you press twice on purpose, and the only one with neither
    a confirmation naming the row (`x`) nor a prefill echoing it (`enter`).

    `reload()` calls `_fill_table`, whose `table.clear(columns=True)` resets the cursor to
    row 0, and pausing does not reorder the pane — so the obvious way to undo a mistaken
    pause silently paused whatever sat on row 0 instead, and the next `r` skipped both.
    """
    _seed(db, name="Gym", cost=50.0, category="entertainment")
    _seed(db, name="Streaming", cost=20.99)
    _seed(db, name="Storage", cost=10.0, category="housing")
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        await _on_recurring(pilot, app)
        table = app.query_one("#money-table")
        await pilot.press("down")
        await pilot.press("down")
        await pilot.pause()
        assert table.cursor_row == 2, "this test would prove nothing without a moved cursor"
        await pilot.press("o")
        await pilot.pause()
        assert {r["name"]: r["active"] for r in list_recurring(db)} == {
            "Gym": 1, "Streaming": 1, "Storage": 0,
        }, "the wrong row was paused"
        assert app.query_one("#money-table").cursor_row == 2, "the cursor left the row it acted on"
        await pilot.press("o")
        await pilot.pause()
    assert {r["name"]: r["active"] for r in list_recurring(db)} == {
        "Gym": 1, "Streaming": 1, "Storage": 1,
    }, "a second o did not undo the first"


async def test_o_on_an_empty_recurring_pane_says_so(make_app, db):
    """The one state where `o` looks unbound. `x` already explains itself here and `r`
    reports rolling nothing; silence is what a dropped keypress looks like, and this is
    the pane you land on before adding your first subscription."""
    said = []
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        await _on_recurring(pilot, app)
        app.notify = lambda msg, **kw: said.append(str(msg))
        await pilot.press("o")
        await pilot.pause()
    assert said, "o was silent on an empty pane"
    assert "s" in said[0], f"the toast should point at the key that adds one: {said[0]}"
