import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from daybook.money import add_expense, upsert_budget

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


async def money(pilot, app):
    await pilot.press("2")
    await pilot.pause()
    return app.query_one("#money")


def _cells(app):
    t = app.query_one("#money-table")
    return [[str(c) for c in t.get_row_at(i)] for i in range(t.row_count)]


# ── sort ─────────────────────────────────────────────────────────────────
async def test_sort_by_cost_then_toggle_direction(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await money(pilot, app)
        await pilot.press("c")
        await pilot.pause()
        assert (m.view.sort_field, m.view.sort_desc) == ("amount", True)
        await pilot.press("c")
        assert m.view.sort_desc is False


async def test_sort_key_switch_resets_to_descending(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await money(pilot, app)
        await pilot.press("c")
        await pilot.press("c")
        await pilot.press("d")
        assert (m.view.sort_field, m.view.sort_desc) == ("date", True)


async def test_sorting_from_the_categories_pane_shows_the_rows(make_app, seeded):
    """Sorting is about rows, so it moves you where rows are."""
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await money(pilot, app)
        assert m.view.pane == "categories"
        await pilot.press("c")
        await pilot.pause()
        assert m.view.pane == "expenses"


async def test_sort_order_reaches_the_table(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await money(pilot, app)
        m.view.horizon = "all"
        await pilot.press("c")
        await pilot.pause()
        rows = _cells(app)
    assert any("100.00" in c for c in rows[0])


async def test_sort_by_category_key(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await money(pilot, app)
        await pilot.press("k")
        await pilot.pause()
        assert m.view.sort_field == "category"


# ── filter ───────────────────────────────────────────────────────────────
async def test_slash_filters_the_table(make_app, seeded, type_into):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await money(pilot, app)
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
        m = await money(pilot, app)
        m.view.filter_text = "coffee"
        m.reload()
        await pilot.pause()
        assert "coffee" in m.status_hint()


async def test_sort_direction_shows_in_the_status_hint(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await money(pilot, app)
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
        m = await money(pilot, app)
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
        m = await money(pilot, app)
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
        m = await money(pilot, app)
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
        m = await money(pilot, app)
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
        m = await money(pilot, app)
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
        m = await money(pilot, app)
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
        m = await money(pilot, app)
        m.view.grouped = True
        m.reload()
        await pilot.press("escape")
        await pilot.pause()
        assert m.view.grouped is True


async def test_grouped_chip_shows_in_the_status_hint(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        m = await money(pilot, app)
        await pilot.press("G")
        await pilot.pause()
        assert "grouped" in m.status_hint()


# ── range ────────────────────────────────────────────────────────────────
async def test_widening_the_horizon_changes_the_header_and_totals(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await money(pilot, app)
        await pilot.press("plus")   # MTD -> 3m, which reaches back into May
        await pilot.pause()
        head = str(app.query_one("#money-head").content)
    assert "MAY" in head.upper() and "AUG" in head.upper()
    assert "185.00" in head


async def test_all_time_label(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await money(pilot, app)
        for _ in range(5):
            await pilot.press("plus")
        await pilot.pause()
        head = str(app.query_one("#money-head").content)
    assert "ALL TIME" in head


async def test_calendar_marker_shown_for_the_current_month(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await money(pilot, app)
        bar = str(app.query_one("#money-bar").content)
    assert "┃" in bar
    assert "day 27 of 31" in bar


async def test_calendar_marker_hidden_for_a_multi_month_range(make_app, seeded):
    """Burn-against-elapsed is meaningless across a quarter, so the marker is
    withheld and the bar says what the budget actually represents."""
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await money(pilot, app)
        await pilot.press("plus")
        await pilot.pause()
        bar = str(app.query_one("#money-bar").content)
    assert "┃" not in bar
    assert "day " not in bar
    assert "summed over" in bar


async def test_calendar_marker_hidden_for_a_past_month(make_app, seeded):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await money(pilot, app)
        await pilot.press("left_square_bracket")
        await pilot.pause()
        bar = str(app.query_one("#money-bar").content)
    assert "┃" not in bar


async def test_multi_month_budget_is_the_sum(make_app, seeded, db):
    upsert_budget(db, month="2026-06", name="Grocery", category="grocery", amount=200)
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await money(pilot, app)
        await pilot.press("plus")
        await pilot.pause()
        head = str(app.query_one("#money-head").content)
    assert "500.00" in head


# ── feedback ─────────────────────────────────────────────────────────────
async def test_expense_write_reports_its_consequence(make_app, seeded, type_into):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await money(pilot, app)
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
        await money(pilot, app)
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
        await money(pilot, app)
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
        await money(pilot, app)
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
        m = await money(pilot, app)
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
        m = await money(pilot, app)
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
