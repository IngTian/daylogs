import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from helpers import go_money

from daylogs.money import add_expense, upsert_budget

TZ = ZoneInfo("America/Toronto")
NOW = dt.datetime(2026, 8, 27, 9, 0, tzinfo=TZ)


@pytest.fixture()
def seeded(db):
    add_expense(db, amount=100.0, description="june shop", category="grocery",
                date="2026-06-10")
    add_expense(db, amount=50.0, description="july dinner", category="restaurant",
                date="2026-07-11")
    add_expense(db, amount=25.0, description="august shop", category="grocery",
                date="2026-08-12")
    add_expense(db, amount=10.0, description="bus pass", category="transport",
                date="2026-08-13")
    upsert_budget(db, month="2026-08", name="Grocery", category="grocery", amount=300)
    return db


def _cells(app):
    t = app.query_one("#money-table")
    return [[str(c) for c in t.get_row_at(i)] for i in range(t.row_count)]


# ── sort ─────────────────────────────────────────────────────────────────
async def test_sort_by_cost_then_toggle_direction(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await go_money(pilot, app)
        await pilot.press("c")
        await pilot.pause()
        assert (m.view.sort_field, m.view.sort_desc) == ("amount", True)
        await pilot.press("c")
        assert m.view.sort_desc is False


async def test_sort_key_switch_resets_to_descending(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await go_money(pilot, app)
        await pilot.press("c")
        await pilot.press("c")
        await pilot.press("d")
        assert (m.view.sort_field, m.view.sort_desc) == ("date", True)


async def test_sorting_from_the_categories_pane_shows_the_rows(make_app, seeded):
    """Sorting is about rows, so it moves you where rows are."""
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await go_money(pilot, app)
        assert m.view.pane == "categories"
        await pilot.press("c")
        await pilot.pause()
        assert m.view.pane == "expenses"


async def test_sort_order_reaches_the_table(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await go_money(pilot, app)
        m.view.horizon = "all"
        await pilot.press("c")
        await pilot.pause()
        rows = _cells(app)
    assert any("100.00" in c for c in rows[0])


async def test_sort_by_category_key(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await go_money(pilot, app)
        await pilot.press("k")
        await pilot.pause()
        assert m.view.sort_field == "category"


# ── filter ───────────────────────────────────────────────────────────────
async def test_slash_filters_the_table(make_app, seeded, type_into):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await go_money(pilot, app)
        m.view.horizon = "all"
        m.reload()
        await pilot.press("slash")
        await type_into(pilot, "shop")
        await pilot.press("enter")
        await pilot.pause()
        assert m.view.filter_text == "shop"
        assert app.query_one("#money-table").row_count == 2


async def test_filter_chip_is_visible_in_the_status_hint(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await go_money(pilot, app)
        m.view.filter_text = "coffee"
        m.reload()
        await pilot.pause()
        assert "coffee" in m.status_hint()


async def test_sort_direction_shows_in_the_status_hint(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await go_money(pilot, app)
        await pilot.press("c")
        await pilot.pause()
        assert "↓cost" in m.status_hint()
        await pilot.press("c")
        await pilot.pause()
        assert "↑cost" in m.status_hint()


# ── drill down ───────────────────────────────────────────────────────────
async def test_enter_on_a_category_drills_into_its_expenses(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await go_money(pilot, app)
        m.view.horizon = "all"
        m.reload()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert m.view.pane == "expenses"
        assert m.view.filter_category is not None
        rows = _cells(app)
    assert rows, "drilled view should show rows"


async def test_escape_unwinds_the_drill_one_step_at_a_time(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await go_money(pilot, app)
        m.view.pane = "expenses"
        m.view.filter_category = "grocery"
        m.view.filter_text = "shop"
        m.reload()
        await pilot.press("escape")
        await pilot.pause()
        assert m.view.filter_text == ""
        assert m.view.filter_category == "grocery"
        await pilot.press("escape")
        await pilot.pause()
        assert m.view.filter_category is None
        assert m.view.pane == "categories"


# ── grouping ─────────────────────────────────────────────────────────────
async def test_capital_g_groups_and_shows_header_rows(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await go_money(pilot, app)
        m.view.horizon = "all"
        m.reload()
        await pilot.press("G")
        await pilot.pause()
        assert m.view.grouped is True
        assert m.view.pane == "expenses"
        flat = [c for row in _cells(app) for c in row]
    assert any("▾" in c or "▸" in c for c in flat)


async def test_groups_are_ordered_by_total_descending(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await go_money(pilot, app)
        m.view.horizon = "all"
        m.view.pane = "expenses"
        m.view.grouped = True
        m.reload()
        await pilot.pause()
        rows = _cells(app)
    headers = [r[1] for r in rows if r[0] in ("▾", "▸")]
    assert headers == ["grocery", "restaurant", "transport"]


async def test_enter_collapses_a_group(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await go_money(pilot, app)
        m.view.horizon = "all"
        m.view.pane = "expenses"
        m.view.grouped = True
        m.reload()
        await pilot.pause()
        before = app.query_one("#money-table").row_count
        await pilot.press("enter")
        await pilot.pause()
        assert m.view.collapsed
        assert app.query_one("#money-table").row_count < before


async def test_a_collapsed_group_still_shows_its_total(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await go_money(pilot, app)
        m.view.horizon = "all"
        m.view.pane = "expenses"
        m.view.grouped = True
        m.view.collapsed = frozenset({"grocery"})
        m.reload()
        await pilot.pause()
        rows = _cells(app)
    grocery = next(r for r in rows if r[1] == "grocery")
    assert "125.00" in grocery[3]


async def test_escape_does_not_ungroup(make_app, seeded):
    """Grouping is a view preference, not a narrowing — mixing them into one
    undo stack makes `back` unpredictable."""
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await go_money(pilot, app)
        m.view.grouped = True
        m.reload()
        await pilot.press("escape")
        await pilot.pause()
        assert m.view.grouped is True


async def test_grouped_chip_shows_in_the_status_hint(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await go_money(pilot, app)
        await pilot.press("G")
        await pilot.pause()
        assert "grouped" in m.status_hint()


# ── range ────────────────────────────────────────────────────────────────
async def test_zooming_out_widens_the_horizon_and_changes_the_header_and_totals(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        await pilot.press("minus")  # MTD -> 3m, which reaches back into May
        await pilot.pause()
        head = str(app.query_one("#money-head").content)
    assert "MAY" in head.upper() and "AUG" in head.upper()
    assert "185.00" in head


async def test_all_time_label(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        for _ in range(5):
            await pilot.press("minus")
        await pilot.pause()
        head = str(app.query_one("#money-head").content)
    assert "ALL TIME" in head


async def test_calendar_marker_shown_for_the_current_month(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        bar = str(app.query_one("#money-bar").content)
    assert "┃" in bar
    assert "day 27 of 31" in bar


async def test_calendar_marker_hidden_for_a_multi_month_range(make_app, seeded):
    """Burn-against-elapsed is meaningless across a quarter, so the marker is
    withheld and the bar says what the budget actually represents."""
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        await pilot.press("minus")
        await pilot.pause()
        bar = str(app.query_one("#money-bar").content)
    assert "┃" not in bar
    assert "day " not in bar
    assert "summed over" in bar


async def test_calendar_marker_hidden_for_a_past_month(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        await pilot.press("left_square_bracket")
        await pilot.pause()
        bar = str(app.query_one("#money-bar").content)
    assert "┃" not in bar


async def test_multi_month_budget_is_the_sum(make_app, seeded, db):
    upsert_budget(db, month="2026-06", name="Grocery", category="grocery", amount=200)
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        await pilot.press("minus")
        await pilot.pause()
        head = str(app.query_one("#money-head").content)
    assert "500.00" in head


# ── feedback ─────────────────────────────────────────────────────────────
async def test_expense_write_reports_its_consequence(make_app, seeded, type_into):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        seen = []
        app.notify = lambda msg, **kw: seen.append(str(msg))
        await pilot.press("e")
        await type_into(pilot, "12.40 lunch !restaurant")
        await pilot.press("enter")
        await pilot.pause()
    assert any("12.40" in m for m in seen)
    assert any("restaurant" in m for m in seen)


async def test_expense_feedback_warns_when_over_budget(make_app, db, type_into):
    upsert_budget(db, month="2026-08", name="Restaurant", category="restaurant", amount=20)
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        seen = []
        app.notify = lambda msg, **kw: seen.append(str(msg))
        await pilot.press("e")
        await type_into(pilot, "50 dinner !restaurant")
        await pilot.press("enter")
        await pilot.pause()
    assert any("⚠" in m for m in seen), f"no over-budget warning: {seen}"


async def test_budget_write_reports_spent_and_left(make_app, seeded, type_into):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        seen = []
        app.notify = lambda msg, **kw: seen.append(str(msg))
        await pilot.press("b")
        await type_into(pilot, "500 !grocery")
        await pilot.press("enter")
        await pilot.pause()
    assert any("spent" in m and "left" in m for m in seen), f"{seen}"


async def test_recurring_write_reports_the_monthly_equivalent(make_app, db, type_into):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        seen = []
        app.notify = lambda msg, **kw: seen.append(str(msg))
        await pilot.press("s")
        await type_into(pilot, "120 cloud !subscriptions #annually")
        await pilot.press("enter")
        await pilot.pause()
    assert any("10.00/mo" in m for m in seen), f"{seen}"


async def test_delete_confirm_names_the_expense(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await go_money(pilot, app)
        m.view.pane = "expenses"
        m.view.horizon = "all"
        m.reload()
        await pilot.pause()
        seen = []
        app.notify = lambda msg, **kw: seen.append(str(msg))
        await pilot.press("x")
        await pilot.pause()
    assert any("shop" in m or "dinner" in m or "bus" in m for m in seen), f"{seen}"


async def test_delete_on_a_group_header_is_refused(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await go_money(pilot, app)
        m.view.pane = "expenses"
        m.view.horizon = "all"
        m.view.grouped = True
        m.reload()
        await pilot.pause()
        seen = []
        app.notify = lambda msg, **kw: seen.append(str(msg))
        await pilot.press("x")
        await pilot.pause()
    assert any("group header" in m for m in seen), f"{seen}"


# ── esc has to repaint what it changed ───────────────────────────────────


async def test_escape_out_of_a_drilled_category_repaints_the_table(make_app, seeded):
    """`esc` unwound `MoneyView` and then nothing redrew, so the table kept showing the
    category you had just left while the footer chip already said you were out of it.

    Every tab defines `key_back`, so the app-level handler that did the `reload()` was
    never reached — the tab's own handler always won the lookup. It mutated state and
    returned a bool to a caller that did not exist.
    """
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 40)) as pilot:
        m = await go_money(pilot, app)
        m.view.filter_category = "grocery"
        m.view.pane = "expenses"
        m.reload()
        await pilot.pause()
        drilled = _cells(app)
        assert all("grocery" in " ".join(row) for row in drilled), drilled

        await pilot.press("escape")
        await pilot.pause()
        assert m.view.filter_category is None, "the view did not unwind"
        assert m.view.pane == "categories"
        after = _cells(app)
    assert after != drilled, "esc changed the view and the table kept the old rows"
    assert any("transport" in " ".join(row) for row in after), (
        f"the categories pane did not come back: {after}"
    )


async def test_escape_out_of_a_text_filter_repaints_the_table(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 40)) as pilot:
        m = await go_money(pilot, app)
        m.view.pane = "expenses"
        m.view.filter_text = "bus"
        m.reload()
        await pilot.pause()
        filtered = _cells(app)
        assert len(filtered) == 1, filtered

        await pilot.press("escape")
        await pilot.pause()
        assert m.view.filter_text == ""
        after = _cells(app)
    assert len(after) > len(filtered), f"the filter cleared but the rows did not: {after}"


async def test_escape_repaints_the_pane_strip_too(make_app, seeded):
    """The strip bolds the active pane. Unwinding to `categories` without a repaint left
    it bolding the pane you had left."""
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 40)) as pilot:
        m = await go_money(pilot, app)
        m.view.filter_category = "grocery"
        m.view.pane = "expenses"
        m.reload()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        strip = str(app.query_one("#money-panes").content)
    assert "[b]categories[/b]" in strip, f"the strip still marks the old pane: {strip!r}"


async def test_escape_with_nothing_to_unwind_changes_nothing(make_app, seeded):
    """esc never quits, and on a tab with nothing narrowed it is a no-op.

    "No-op" includes not repainting. `_fill_table` clears the table with
    `columns=True`, which resets the cursor to row 0 — so an unconditional reload would
    silently throw away whichever row you had selected, the same hazard body_tab's
    estimate indicator is written to avoid. That is why the repaint is guarded by
    whether anything actually unwound.
    """
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 40)) as pilot:
        m = await go_money(pilot, app)
        await pilot.pause()
        table = app.query_one("#money-table")
        assert table.row_count >= 2, f"the seed needs two rows to move between: {table.row_count}"
        table.focus()
        table.move_cursor(row=1)
        await pilot.pause()
        before, cursor = _cells(app), table.cursor_row
        assert cursor == 1, "the cursor did not move, so the assertion below proves nothing"

        await pilot.press("escape")
        await pilot.pause()
        assert app.is_running
        assert _cells(app) == before
        assert m.view.filter_category is None
        assert table.cursor_row == cursor, "esc repainted and lost the selected row"


async def test_escape_on_body_and_day_is_a_no_op(make_app, seeded):
    """Neither tab narrows, so neither has anything to unwind — and esc must still not
    quit, which is the property the binding exists for."""
    from helpers import go_body, go_day

    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 40)) as pilot:
        await go_body(pilot, app)
        await pilot.press("escape")
        await pilot.pause()
        assert app.is_running
        await go_day(pilot, app)
        await pilot.press("escape")
        await pilot.pause()
        assert app.is_running


# ── what the numbers on screen say they cover ───────────────────────────────
async def test_a_one_month_span_names_the_month_instead_of_summing_it(make_app, seeded):
    """"budget summed over 1 months" is wrong twice in five words.

    Nothing was summed, and that is not a plural. It is reachable with keys alone: the
    `else` branch takes every horizon except MTD-on-the-current-month, so a one-week window
    and a past MTD month both land there. Naming the month is also the truer word below a
    month-wide horizon — `summarize_span` filters spend by date and sums budgets by
    calendar month, so at `1w` the 35.00 is the week's while the 300.00 cap is all of
    August.
    """
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 40)) as pilot:
        m = await go_money(pilot, app)
        m.view.horizon = "1w"
        m.view.anchor = "2026-08-15"
        m.reload()
        await pilot.pause()
        assert m.view.months() == ["2026-08"], "the window is not inside one month"
        bar = str(app.query_one("#money-bar").content)
    assert "1 months" not in bar, bar
    assert "budget for 2026-08" in bar, bar


async def test_budget_toast_says_which_window_its_figures_cover(make_app, seeded, type_into):
    """The month is the one on screen; the figures are the whole span's.

    `_budget_month` writes to the right-hand edge of the span — deliberately, so `[` and a
    budget key agree — and the toast states it. `spent` and `left` come from
    `summarize_span` over the *whole* span, so on a three-month horizon this read "for
    2026-08 · 125.00 spent" while August's grocery spend is 25.00: the other 100.00 is
    June's. Both halves are true and the sentence joining them was not.
    """
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 40)) as pilot:
        m = await go_money(pilot, app)
        await pilot.press("minus")  # MTD -> 3m, which reaches back into June
        await pilot.pause()
        assert len(m.view.months()) > 1, "the horizon did not widen past one month"
        said = []
        app.notify = lambda msg, **kw: said.append(str(msg))
        await pilot.press("b")
        await type_into(pilot, "500 !grocery")
        await pilot.press("enter")
        await pilot.pause()
    assert said, "no toast"
    assert "for 2026-08" in said[0], said[0]
    assert "125.00 spent this range" in said[0], said[0]


# ── esc out of the filter prompt ────────────────────────────────────────────
async def test_one_esc_cancels_the_filter_prompt_and_a_second_clears_the_filter(
    make_app, seeded, type_into
):
    """The two presses the hint has to describe.

    `escape` is claimed by `InlinePrompt.on_key`, which closes the prompt and touches no
    view state, so the filter is still on and the table still short. Clearing it is the
    tab's `esc` — `key_back` -> `MoneyView.back` — on the press after. The hint said "esc
    clears it", which reads as one.
    """
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 40)) as pilot:
        m = await go_money(pilot, app)
        m.view.horizon = "all"
        m.reload()
        await pilot.press("slash")
        await type_into(pilot, "shop")
        await pilot.press("enter")
        await pilot.pause()
        assert m.view.filter_text == "shop", "the filter never went on"
        filtered = app.query_one("#money-table").row_count

        await pilot.press("slash")  # re-opens prefilled with the live filter
        await pilot.pause()
        assert app.prompt.value == "shop"
        await pilot.press("escape")
        await pilot.pause()
        assert app.prompt.is_open is False
        assert m.view.filter_text == "shop", "one esc cleared it — then the hint may say so"
        assert app.query_one("#money-table").row_count == filtered

        await pilot.press("escape")
        await pilot.pause()
        assert m.view.filter_text == ""
        assert app.query_one("#money-table").row_count > filtered


async def test_submitting_an_emptied_filter_line_leaves_the_filter_alone(
    make_app, seeded, type_into
):
    """The other way a user reaches for "clear this".

    `on_input_submitted` treats an empty value as a cancel — closes, focuses the table, and
    never calls `handle_prompt` — so backspacing the line out and pressing enter changes
    nothing. That is app-wide policy, not a Money decision, which is why the hint stopped
    implying otherwise instead of the path being rerouted.
    """
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 40)) as pilot:
        m = await go_money(pilot, app)
        m.view.horizon = "all"
        m.reload()
        await pilot.press("slash")
        await type_into(pilot, "shop")
        await pilot.press("enter")
        await pilot.pause()
        assert m.view.filter_text == "shop"

        await pilot.press("slash")
        await pilot.pause()
        for _ in range(len("shop")):
            await pilot.press("backspace")
        assert app.prompt.value == ""
        await pilot.press("enter")
        await pilot.pause()
        assert m.view.filter_text == "shop"
