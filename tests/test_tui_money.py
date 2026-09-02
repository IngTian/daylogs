import datetime as dt

from helpers import all_expenses, go_money

from daylogs.money import (
    add_expense,
    list_budget,
    list_recurring,
    upsert_budget,
    upsert_recurring,
)


async def test_e_logs_an_expense_with_inferred_category(make_app, db, type_into):
    app = make_app()
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        await pilot.press("e")
        await type_into(pilot, "12.40 lunch !restaurant")
        await pilot.press("enter")
        await pilot.pause()
    rows = all_expenses(db)
    assert len(rows) == 1
    assert (rows[0]["amount"], rows[0]["category"], rows[0]["description"]) == (
        12.40,
        "restaurant",
        "lunch",
    )


async def test_e_without_a_category_writes_other_and_reopens_for_correction(
    make_app, db, type_into
):
    app = make_app()
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        await pilot.press("e")
        await type_into(pilot, "12.40 lunch")
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open is True
        assert app.prompt.label == "fix category"
        assert "12.40 lunch" in app.prompt.value
    assert all_expenses(db)[0]["category"] == "other"


async def test_fixing_the_category_does_not_loop_forever(make_app, db, type_into):
    app = make_app()
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        await pilot.press("e")
        await type_into(pilot, "12.40 lunch")
        await pilot.press("enter")
        await pilot.pause()
        app.prompt.value = "12.40 lunch !restaurant"
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open is False
    cats = sorted(r["category"] for r in all_expenses(db))
    assert cats == ["other", "restaurant"]


async def test_e_rejects_a_missing_amount_without_writing(make_app, db, type_into):
    app = make_app()
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        await pilot.press("e")
        await type_into(pilot, "lunch")
        await pilot.press("enter")
        await pilot.pause()
        assert app.is_running is True
    assert all_expenses(db) == []


async def test_refund_is_accepted_as_a_negative_amount(make_app, db):
    app = make_app()
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        await pilot.press("e")
        app.prompt.value = "-24.99 returned shoes !entertainment"
        await pilot.press("enter")
        await pilot.pause()
    assert all_expenses(db)[0]["amount"] == -24.99


async def test_b_sets_a_budget_line(make_app, db, type_into):
    app = make_app()
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        await pilot.press("b")
        await type_into(pilot, "500 !grocery")
        await pilot.press("enter")
        await pilot.pause()
        month = app.today()[:7]
    rows = list_budget(db, month=month)
    assert len(rows) == 1
    assert (rows[0]["amount"], rows[0]["category"], rows[0]["name"]) == (
        500.0,
        "grocery",
        "Grocery",
    )


async def test_b_rejects_an_unknown_category(make_app, db, type_into):
    app = make_app()
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        await pilot.press("b")
        await type_into(pilot, "500 nonsense")
        await pilot.press("enter")
        await pilot.pause()
        month = app.today()[:7]
        assert app.is_running is True
    assert list_budget(db, month=month) == []


async def test_s_adds_a_recurring_item_and_shows_that_pane(make_app, db, type_into):
    app = make_app()
    async with app.run_test() as pilot:
        money_tab = await go_money(pilot, app)
        await pilot.press("s")
        await type_into(pilot, "20.99 streaming !subscriptions")
        await pilot.press("enter")
        await pilot.pause()
        assert money_tab.view.pane == "recurring"
    rows = list_recurring(db)
    assert len(rows) == 1
    assert (rows[0]["name"], rows[0]["monthly_cost"]) == ("streaming", 20.99)


async def test_annual_recurring_stores_monthly_equivalent(make_app, db):
    app = make_app()
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        await pilot.press("s")
        app.prompt.value = "120 cloud storage !subscriptions #annually"
        await pilot.press("enter")
        await pilot.pause()
    row = list_recurring(db)[0]
    assert (row["cycle"], row["monthly_cost"]) == ("annually", 10.0)


async def test_r_rolls_recurring_into_the_viewed_month(make_app, db, type_into):
    app = make_app()
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        await pilot.press("s")
        await type_into(pilot, "20.99 streaming !subscriptions")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        month = app.today()[:7]
    rows = list_budget(db, month=month)
    assert [r["source"] for r in rows] == ["recurring"]
    assert rows[0]["amount"] == 20.99


async def test_bracket_keys_move_the_month(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        money_tab = await go_money(pilot, app)
        start = money_tab.view.anchor
        await pilot.press("left_square_bracket")
        assert money_tab.view.anchor < start
        await pilot.press("right_square_bracket")
        assert money_tab.view.anchor == start


async def test_month_step_crosses_a_year_boundary(make_app):
    app = make_app(now=lambda: dt.datetime(2026, 1, 15, 10, 0))
    async with app.run_test() as pilot:
        money_tab = await go_money(pilot, app)
        assert money_tab.view.anchor == "2026-01-15"
        await pilot.press("left_square_bracket")
        assert money_tab.view.anchor == "2025-12-15"


async def test_tab_cycles_sub_panes(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        money_tab = await go_money(pilot, app)
        assert money_tab.view.pane == "categories"
        await pilot.press("tab")
        assert money_tab.view.pane == "expenses"
        await pilot.press("tab")
        assert money_tab.view.pane == "recurring"
        await pilot.press("tab")
        assert money_tab.view.pane == "categories"


async def test_x_deletes_the_selected_expense_and_u_restores_it(make_app, db):
    app = make_app()
    # `app.today()`, not `dt.date.today()`: the app's clock is pinned to
    # cfg.timezone while `dt.date.today()` follows the process TZ. The two straddle
    # midnight for part of every day, and then the seeded row falls outside the MTD
    # span, the expense pane is empty, and `x` has no row to delete. Reproduce with
    # `TZ=UTC pytest` any Toronto evening.
    today = app.today()
    add_expense(
        db, amount=12.40, description="lunch", category="restaurant", date=today
    )
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        await pilot.press("tab")
        await pilot.pause()
        await pilot.press("x")
        await pilot.press("y")
        await pilot.pause()
        assert all_expenses(db) == []
        await pilot.press("u")
        await pilot.pause()
    rows = all_expenses(db)
    assert len(rows) == 1 and rows[0]["description"] == "lunch"


async def test_x_on_the_categories_pane_explains_itself(make_app, db):
    app = make_app()
    today = app.today()          # the app's clock, not the process TZ — see above
    add_expense(db, amount=1.0, description="x", category="grocery", date=today)
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        await pilot.press("x")
        await pilot.pause()
        assert app.is_running is True
    assert len(all_expenses(db)) == 1


async def test_x_deletes_a_recurring_row(make_app, db, type_into):
    app = make_app()
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        await pilot.press("s")
        await type_into(pilot, "20.99 streaming !subscriptions")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("x")
        await pilot.press("y")
        await pilot.pause()
    assert list_recurring(db) == []


async def test_header_shows_spend_against_budget(make_app, db):
    app = make_app()
    # Two date traps meet here, and the second one bit after the first was fixed.
    #
    # The month: on a month's last day after 20:00 Toronto, `dt.date.today()`
    # under `TZ=UTC` is already the 1st of the next month, so the rows land in a
    # month the app is not showing and the header reads `spent 0.00`. Hence
    # `app.today()` rather than the process clock.
    #
    # The *day*: these tests used to seed `f"{month}-10"`, which is in the future
    # for the first nine days of any month — and the default horizon is
    # month-to-date, so the expense fell outside the window and the header read
    # `spent 0.00` again. It broke on 2026-09-02. Seeding on `app.today()` is
    # inside every month-to-date span by construction, so there is no day left to
    # be wrong about.
    month = app.today()[:7]
    upsert_budget(db, month=month, name="Grocery", category="grocery", amount=500)
    add_expense(
        db, amount=412.0, description="shop", category="grocery", date=app.today()
    )
    async with app.run_test() as pilot:
        money_tab = await go_money(pilot, app)
        money_tab.reload()
        await pilot.pause()
        head = str(app.query_one("#money-head").content)
    assert "412.00" in head and "500.00" in head
    assert "left" in head


async def test_header_says_over_when_past_budget(make_app, db):
    app = make_app()
    month = app.today()[:7]      # the app's clock, not the process TZ — see above
    upsert_budget(db, month=month, name="Restaurant", category="restaurant", amount=200)
    add_expense(
        db, amount=289.0, description="dinner", category="restaurant", date=app.today()
    )
    async with app.run_test() as pilot:
        money_tab = await go_money(pilot, app)
        money_tab.reload()
        await pilot.pause()
        head = str(app.query_one("#money-head").content)
    assert "over" in head


async def test_burn_bar_shows_percentage_and_calendar_progress(make_app, db):
    app = make_app()
    month = app.today()[:7]      # the app's clock, not the process TZ — see above
    upsert_budget(db, month=month, name="Grocery", category="grocery", amount=100)
    add_expense(
        db, amount=50.0, description="shop", category="grocery", date=app.today()
    )
    async with app.run_test() as pilot:
        money_tab = await go_money(pilot, app)
        money_tab.reload()
        await pilot.pause()
        bar = str(app.query_one("#money-bar").content)
    assert "50%" in bar
    assert "day " in bar
    assert "┃" in bar


async def test_over_budget_category_is_flagged_in_the_table(make_app, db):
    app = make_app()
    month = app.today()[:7]      # the app's clock, not the process TZ — see above
    upsert_budget(db, month=month, name="Restaurant", category="restaurant", amount=200)
    add_expense(
        db, amount=289.0, description="dinner", category="restaurant", date=app.today()
    )
    async with app.run_test() as pilot:
        money_tab = await go_money(pilot, app)
        money_tab.reload()
        await pilot.pause()
        table = app.query_one("#money-table")
        cells = [str(c) for c in table.get_row_at(0)]
    assert any("⚠" in c for c in cells)


async def test_empty_month_renders_without_crashing(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        money_tab = await go_money(pilot, app)
        money_tab.reload()
        await pilot.pause()
        assert "0.00" in str(app.query_one("#money-head").content)


# ── panels ──────────────────────────────────────────────────────────────────


def _panel(app, panel_id):
    from textual.widgets import Static

    content = app.query_one(panel_id, Static).content
    return content if isinstance(content, str) else content.plain


async def test_panels_show_a_net_negative_category_with_its_amount(make_app, db):
    """A reimbursed bill lands as a negative expense, so a category can net below
    zero. Filtering those rows out of the panels made WHERE IT WENT add up to gross
    spend while the header showed the net, with nothing on screen explaining it."""
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    add_expense(db, amount=300.0, description="gas", category="transport", date="2026-08-04")
    add_expense(db, amount=40.0, description="dentist", category="other", date="2026-08-05")
    add_expense(
        db, amount=-240.0, description="dentist refund", category="other", date="2026-08-06"
    )
    app = make_app(now=now)
    async with app.run_test(size=(110, 34)) as pilot:
        await go_money(pilot, app)
        share = _panel(app, "#share-body")
        budget = _panel(app, "#budget-body")
    assert "-200.00" in share
    assert "-200.00" in budget
    # Share is of gross spend, so the one positive category owns all of it.
    assert "100.0%" in share
    # And the negative row gets no share rather than a nonsense negative percent.
    assert "-200.0%" not in share


async def test_panels_shares_total_one_hundred_percent_alongside_a_refund(make_app, db):
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    add_expense(db, amount=300.0, description="gas", category="transport", date="2026-08-04")
    add_expense(db, amount=100.0, description="food", category="grocery", date="2026-08-04")
    add_expense(db, amount=-200.0, description="refund", category="other", date="2026-08-06")
    app = make_app(now=now)
    async with app.run_test(size=(110, 34)) as pilot:
        await go_money(pilot, app)
        share = _panel(app, "#share-body")
    assert "75.0%" in share
    assert "25.0%" in share


async def test_budget_panel_rows_are_uniform_width_with_a_refund_present(make_app, db):
    """The unclamped bar emitted 58 cells for a 14-cell bar and pushed the amounts
    off the panel."""
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    upsert_budget(db, month="2026-08", name="other", category="other", amount=200.0)
    add_expense(db, amount=40.0, description="dentist", category="other", date="2026-08-05")
    add_expense(
        db, amount=-240.0, description="dentist refund", category="other", date="2026-08-06"
    )
    add_expense(db, amount=300.0, description="gas", category="transport", date="2026-08-04")
    app = make_app(now=now)
    async with app.run_test(size=(110, 34)) as pilot:
        await go_money(pilot, app)
        lines = _panel(app, "#budget-body").splitlines()
    assert len(lines) == 2
    assert len({len(line) for line in lines}) == 1
    assert "-200.00" in "\n".join(lines)


# ── empty-budget month, and good/bad colour ─────────────────────────────────


async def test_no_budget_month_names_the_fix_instead_of_showing_zero(make_app, db):
    """"0.00 budget / 1,234.00 over" is arithmetically true and reads as stale
    data. The real state is "nobody rolled this month yet"."""
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    add_expense(db, amount=300.0, description="gas", category="transport", date="2026-08-04")
    upsert_recurring(db, name="Rent", category="housing", cost=750, cycle="monthly")
    upsert_recurring(db, name="Phone", category="utilities", cost=60, cycle="monthly")
    app = make_app(now=now)
    async with app.run_test(size=(110, 34)) as pilot:
        await go_money(pilot, app)
        head = str(app.query_one("#money-head").content)
        bar_shown = app.query_one("#money-bar").display
    assert "r rolls 2 recurring" in head
    assert "810.00" in head
    assert "0.00 budget" not in head
    assert "over" not in head
    assert bar_shown is False


async def test_no_budget_and_no_recurring_points_at_b(make_app, db):
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    add_expense(db, amount=300.0, description="gas", category="transport", date="2026-08-04")
    app = make_app(now=now)
    async with app.run_test(size=(110, 34)) as pilot:
        await go_money(pilot, app)
        head = str(app.query_one("#money-head").content)
    assert "press b" in head


async def test_burn_bar_returns_once_a_budget_exists(make_app, db):
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    add_expense(db, amount=300.0, description="gas", category="transport", date="2026-08-04")
    upsert_budget(db, month="2026-08", name="Gas", category="transport", amount=500)
    app = make_app(now=now)
    async with app.run_test(size=(110, 34)) as pilot:
        await go_money(pilot, app)
        head = str(app.query_one("#money-head").content)
        # Read inside the context: after run_test() exits the widget is torn down
        # and `display` reports False regardless of what was rendered.
        bar_shown = app.query_one("#money-bar").display
    assert bar_shown is True
    assert "200.00 left" in head


async def test_over_budget_is_coloured_bad_and_under_budget_good(make_app, db):
    from daylogs.tui.widgets import BAD, GOOD

    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    upsert_budget(db, month="2026-08", name="Gas", category="transport", amount=100)
    add_expense(db, amount=300.0, description="gas", category="transport", date="2026-08-04")
    app = make_app(now=now)
    async with app.run_test(size=(110, 34)) as pilot:
        await go_money(pilot, app)
        head = str(app.query_one("#money-head").content)
        panel = _panel(app, "#budget-body")
    assert BAD in head
    assert GOOD not in head
    assert BAD in panel


async def test_a_refunded_category_is_not_coloured_as_an_overrun(make_app, db):
    """A negative spend is under every cap; painting it red would be nonsense."""
    from daylogs.tui.widgets import BAD

    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    upsert_budget(db, month="2026-08", name="Other", category="other", amount=100)
    add_expense(db, amount=-200.0, description="refund", category="other", date="2026-08-06")
    app = make_app(now=now)
    async with app.run_test(size=(110, 34)) as pilot:
        await go_money(pilot, app)
        panel = _panel(app, "#budget-body")
    assert BAD not in panel


# ── editing a row with enter ─────────────────────────────────────────────────


async def test_enter_on_a_category_still_drills_in(make_app, db):
    """enter acts on what's under the cursor, so the two behaviours it already had
    must survive the addition of a third."""
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    add_expense(db, amount=12.0, description="lunch", category="restaurant", date="2026-08-04")
    app = make_app(now=now)
    async with app.run_test(size=(120, 34)) as pilot:
        money_tab = await go_money(pilot, app)
        await pilot.press("enter")
        await pilot.pause()
        pane, filtered, prompt_open = (
            money_tab.view.pane,
            money_tab.view.filter_category,
            app.prompt.is_open,
        )
    assert pane == "expenses"
    assert filtered == "restaurant"
    assert prompt_open is False, "a category must not open an edit prompt"


async def test_enter_on_a_group_header_still_folds_it(make_app, db):
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    add_expense(db, amount=12.0, description="lunch", category="restaurant", date="2026-08-04")
    app = make_app(now=now)
    async with app.run_test(size=(120, 34)) as pilot:
        money_tab = await go_money(pilot, app)
        await pilot.press("tab")            # -> expenses pane
        await pilot.press("G")              # group it
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        collapsed, prompt_open = money_tab.view.collapsed, app.prompt.is_open
    assert "restaurant" in collapsed
    assert prompt_open is False, "a group header must not open an edit prompt"


async def test_enter_on_an_expense_row_edits_it_in_place(make_app, db, type_into):
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    add_expense(db, amount=12.0, description="lunch", category="restaurant", date="2026-08-04")
    original = all_expenses(db)[0]["id"]
    app = make_app(now=now)
    async with app.run_test(size=(120, 34)) as pilot:
        await go_money(pilot, app)
        await pilot.press("tab")            # -> expenses pane
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.label == "expense"
        assert "lunch" in app.prompt.value
        app.prompt.value = ""
        await type_into(pilot, "14.50 lunch out !grocery @2026-08-04")
        await pilot.press("enter")
        await pilot.pause()
    rows = all_expenses(db)
    assert len(rows) == 1, "an edit must not insert a second row"
    assert rows[0]["id"] == original
    assert (rows[0]["amount"], rows[0]["description"], rows[0]["category"]) == (
        14.50,
        "lunch out",
        "grocery",
    )
    assert rows[0]["date"] == "2026-08-04"


async def test_editing_an_expense_preserves_created_at(make_app, db, type_into):
    """Implementing edit as delete+re-add would reset created_at and issue a new id."""
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    add_expense(db, amount=12.0, description="lunch", category="restaurant", date="2026-08-04")
    before = db.execute("SELECT created_at FROM expense").fetchone()["created_at"]
    app = make_app(now=now)
    async with app.run_test(size=(120, 34)) as pilot:
        await go_money(pilot, app)
        await pilot.press("tab")
        await pilot.press("enter")
        await pilot.pause()
        app.prompt.value = ""
        await type_into(pilot, "14.50")
        await pilot.press("enter")
        await pilot.pause()
    assert db.execute("SELECT created_at FROM expense").fetchone()["created_at"] == before


async def test_undoing_an_expense_edit_restores_it(make_app, db, type_into):
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    add_expense(db, amount=12.0, description="lunch", category="restaurant", date="2026-08-04")
    app = make_app(now=now)
    async with app.run_test(size=(120, 34)) as pilot:
        await go_money(pilot, app)
        await pilot.press("tab")
        await pilot.press("enter")
        await pilot.pause()
        app.prompt.value = ""
        await type_into(pilot, "99.99 oops !housing @2026-08-04")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("u")
        await pilot.pause()
    rows = all_expenses(db)
    assert len(rows) == 1
    assert (rows[0]["amount"], rows[0]["description"], rows[0]["category"]) == (
        12.0,
        "lunch",
        "restaurant",
    )


async def test_enter_on_a_recurring_row_renames_without_duplicating(make_app, db, type_into):
    """The reason update_recurring exists: the `s` prompt upserts by name, so a
    renamed edit through that path INSERTs a second active row."""
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    upsert_recurring(db, name="streaming", category="subscriptions", cost=20, cycle="monthly")
    app = make_app(now=now)
    async with app.run_test(size=(120, 34)) as pilot:
        await go_money(pilot, app)
        await pilot.press("tab")
        await pilot.press("tab")            # -> recurring pane
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.label == "recurring"
        app.prompt.value = ""
        await type_into(pilot, "24.99 streaming plus !subscriptions #monthly")
        await pilot.press("enter")
        await pilot.pause()
    rows = list_recurring(db)
    assert len(rows) == 1, "a rename must not insert a second row"
    assert rows[0]["name"] == "streaming plus"
    assert rows[0]["monthly_cost"] == 24.99, "the derived column is recomputed"


async def test_a_colliding_recurring_rename_is_rejected_cleanly(make_app, db, type_into):
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    upsert_recurring(db, name="Rent", category="housing", cost=750, cycle="monthly")
    upsert_recurring(db, name="Gym", category="other", cost=40, cycle="monthly")
    app = make_app(now=now)
    async with app.run_test(size=(120, 34)) as pilot:
        await go_money(pilot, app)
        await pilot.press("tab")
        await pilot.press("tab")
        await pilot.pause()
        # The pane sorts by cost, so Rent (750) is row 0 — step onto Gym, whose
        # rename genuinely collides.
        await pilot.press("down")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert "Gym" in app.prompt.value, "precondition: editing Gym, not Rent"
        app.prompt.value = ""
        await type_into(pilot, "40 Rent !other #monthly")
        await pilot.press("enter")
        await pilot.pause()
        still_open = app.prompt.is_open
    assert still_open is True, "the prompt keeps the text so the name can be fixed"
    assert len(list_recurring(db)) == 2
async def test_escaping_an_expense_edit_does_not_corrupt_next_entry(make_app, db, type_into):
    """If user arms an expense edit, presses escape, then submits a fresh entry,
    that fresh entry must INSERT, not UPDATE the abandoned row.

    The clock is pinned and the prompt is asserted open, because the expense table
    filters by month, so an unpinned `now` leaves it empty from Sept 1, `enter`
    arms nothing, and the test passes with the fix removed.
    """
    import datetime as dt

    add_expense(db, amount=12.0, description="original", category="restaurant", date="2026-08-28")
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    app = make_app(now=now)
    async with app.run_test(size=(120, 34)) as pilot:
        await go_money(pilot, app)
        await pilot.press("tab")
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open, "no edit was armed, so this test proves nothing"
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("e")
        await type_into(pilot, "25 fresh !grocery")
        await pilot.press("enter")
        await pilot.pause()
    rows = all_expenses(db)
    assert len(rows) == 2, "must have two expense rows"
    assert any(r["description"] == "original" and r["amount"] == 12.0 for r in rows)
    assert any(r["description"] == "fresh" and r["amount"] == 25.0 for r in rows)


async def test_escaping_a_recurring_edit_does_not_corrupt_next_entry(make_app, db, type_into):
    """If user arms a recurring edit, presses escape, then submits a fresh entry,
    that fresh entry must INSERT, not UPDATE the abandoned row."""
    upsert_recurring(db, name="Original", cost=20, cycle="monthly", category="subscriptions")
    app = make_app()
    async with app.run_test(size=(120, 34)) as pilot:
        await go_money(pilot, app)
        await pilot.press("tab")
        await pilot.press("tab")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("s")
        await type_into(pilot, "10 Fresh !other")
        await pilot.press("enter")
        await pilot.pause()
    rows = list_recurring(db)
    assert len(rows) == 2, "must have two recurring rows"
    assert any(r["name"] == "Original" and r["cost"] == 20 for r in rows)
    assert any(r["name"] == "Fresh" and r["cost"] == 10 for r in rows)


async def test_empty_submit_on_expense_edit_does_not_corrupt_next_entry(make_app, db, type_into):
    """If user arms an expense edit, clears the line, submits empty, then submits a
    fresh entry, that fresh entry must INSERT, not UPDATE the abandoned row.

    The clock is pinned and the prompt asserted open: the Money table defaults to
    MTD, so on an unpinned clock this row falls outside the window from September
    and `enter` would arm nothing, passing every assertion below for free.
    """
    add_expense(db, amount=12.0, description="original", category="restaurant", date="2026-08-28")
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    app = make_app(now=now)
    async with app.run_test(size=(120, 34)) as pilot:
        await go_money(pilot, app)
        await pilot.press("tab")
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open, "no edit was armed, so this test proves nothing"
        app.prompt.value = ""
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("e")
        await type_into(pilot, "25 fresh !grocery")
        await pilot.press("enter")
        await pilot.pause()
    rows = all_expenses(db)
    assert len(rows) == 2, "must have two expense rows"
    assert any(r["description"] == "original" and r["amount"] == 12.0 for r in rows)
    assert any(r["description"] == "fresh" and r["amount"] == 25.0 for r in rows)


async def test_empty_submit_on_recurring_edit_does_not_corrupt_next_entry(make_app, db, type_into):
    """If user arms a recurring edit, clears the line, submits empty, then submits a
    fresh entry, that fresh entry must INSERT, not UPDATE the abandoned row."""
    upsert_recurring(db, name="Original", cost=20, cycle="monthly", category="subscriptions")
    app = make_app()
    async with app.run_test(size=(120, 34)) as pilot:
        await go_money(pilot, app)
        await pilot.press("tab")
        await pilot.press("tab")
        await pilot.press("enter")
        await pilot.pause()
        app.prompt.value = ""
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("s")
        await type_into(pilot, "10 Fresh !other")
        await pilot.press("enter")
        await pilot.pause()
    rows = list_recurring(db)
    assert len(rows) == 2, "must have two recurring rows"
    assert any(r["name"] == "Original" and r["cost"] == 20 for r in rows)
    assert any(r["name"] == "Fresh" and r["cost"] == 10 for r in rows)


async def test_editing_an_expense_can_clear_its_note(make_app, db, type_into):
    """A line that omits ~note must clear the column.

    The clock is pinned because the expense table filters by month, so an unpinned
    `now` leaves it empty from Sept 1 and the test fails outright.
    """
    import datetime as dt

    add_expense(db, amount=12.0, description="lunch", category="restaurant",
                date="2026-08-28", note="receipt in wallet")
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    app = make_app(now=now)
    async with app.run_test(size=(120, 34)) as pilot:
        await go_money(pilot, app)
        await pilot.press("tab")
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open, "no edit was armed, so this test proves nothing"
        app.prompt.value = ""
        await type_into(pilot, "12.00 lunch !restaurant @2026-08-28")
        await pilot.press("enter")
        await pilot.pause()
    rows = all_expenses(db)
    assert len(rows) == 1
    assert rows[0]["note"] == "", "omitting ~note must clear the note"


async def test_editing_an_expense_with_unchanged_prefill_preserves_note(make_app, db, type_into):
    """Submitting the rendered prefill unchanged must keep the note.

    The clock is pinned and the prompt is asserted open, because the expense table
    filters by month, so an unpinned `now` leaves it empty from Sept 1, the prompt
    never opens, and the test becomes vacuous.
    """
    import datetime as dt

    add_expense(db, amount=12.0, description="lunch", category="restaurant",
                date="2026-08-28", note="receipt in wallet")
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    app = make_app(now=now)
    async with app.run_test(size=(120, 34)) as pilot:
        await go_money(pilot, app)
        await pilot.press("tab")
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open, "no edit was armed, so this test proves nothing"
        # The prefill is "12.00 lunch !restaurant @2026-08-28 ~receipt in wallet". Submit unchanged.
        await pilot.press("enter")
        await pilot.pause()
    rows = all_expenses(db)
    assert len(rows) == 1
    assert rows[0]["note"] == "receipt in wallet"


async def test_month_to_date_header_holds_on_the_first_of_the_month(make_app, db):
    """The regression guard for the day-of-month trap, pinned to the worst case.

    Every other test here runs on the real clock, so none of them can fail on the
    day that matters: on the 1st, a month-to-date span is a single day wide, and
    anything seeded on a hardcoded later day sits in the future and is invisible.
    That is the shape that broke four tests on 2026-09-02, and it is the fifth
    date-relative failure in this repo, so it gets a test that does not depend on
    when it runs.
    """
    import datetime as dt
    from zoneinfo import ZoneInfo

    first = dt.datetime(2026, 9, 1, 9, 0, tzinfo=ZoneInfo("America/Toronto"))
    app = make_app(now=lambda: first)
    upsert_budget(db, month="2026-09", name="Grocery", category="grocery", amount=500)
    add_expense(db, amount=412.0, description="shop", category="grocery", date="2026-09-01")
    async with app.run_test() as pilot:
        money_tab = await go_money(pilot, app)
        money_tab.reload()
        await pilot.pause()
        head = str(app.query_one("#money-head").content)
    assert "412.00" in head, f"spend on the 1st vanished from the header: {head!r}"
    assert "500.00" in head
