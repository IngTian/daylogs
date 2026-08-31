import datetime as dt
from zoneinfo import ZoneInfo

from helpers import all_expenses, go_body, go_day, go_money

from daybook.summary import upsert_report

TZ = ZoneInfo("America/Toronto")
NOW = dt.datetime(2026, 8, 27, 9, 0, tzinfo=TZ)


# ── jump to now: the key v1 had no equivalent for ────────────────────────
async def test_t_returns_body_to_today_from_far_away(make_app):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        body = app.query_one("#body")
        body.viewing_date = "2026-03-01"
        body.reload()
        await pilot.press("t")
        await pilot.pause()
        assert body.viewing_date == "2026-08-27"


async def test_t_returns_money_to_this_month(make_app):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        money = app.query_one("#money")
        money.view.anchor = "2026-03-15"
        await pilot.press("t")
        await pilot.pause()
        assert money.view.anchor == "2026-08-27"


async def test_t_on_money_also_clears_filters(make_app):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        money = app.query_one("#money")
        money.view.filter_text = "coffee"
        money.view.filter_category = "grocery"
        await pilot.press("t")
        await pilot.pause()
        assert money.view.filter_text == ""
        assert money.view.filter_category is None


async def test_t_on_summary_returns_to_the_newest_report(make_app, db):
    upsert_report(db, date="2026-08-25", content="older")
    upsert_report(db, date="2026-08-26", content="newer")
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("left_square_bracket")
        await pilot.pause()
        assert app.query_one("#summary").viewing_date == "2026-08-25"
        await pilot.press("t")
        await pilot.pause()
        assert app.query_one("#summary").viewing_date == "2026-08-26"


# ── go to date ───────────────────────────────────────────────────────────
async def test_g_jumps_body_to_a_date(make_app, type_into):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        await pilot.press("g")
        await type_into(pilot, "2026-06-15")
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one("#body").viewing_date == "2026-06-15"


async def test_g_jumps_money_to_a_month(make_app, type_into):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        await pilot.press("g")
        await type_into(pilot, "2026-06")
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one("#money").view.anchor == "2026-06-30"


async def test_g_with_junk_keeps_the_prompt_open(make_app, type_into):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        await pilot.press("g")
        await type_into(pilot, "june")
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open is True
        assert app.prompt.error


# ── sub-views ────────────────────────────────────────────────────────────
async def test_tab_cycles_body_subview(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        body = app.query_one("#body")
        assert body.table_mode == "food"
        await pilot.press("tab")
        assert body.table_mode == "weight"
        await pilot.press("tab")
        assert body.table_mode == "food"


async def test_tab_cycles_money_panes_and_shift_tab_reverses(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        money = app.query_one("#money")
        assert money.view.pane == "categories"
        await pilot.press("tab")
        assert money.view.pane == "expenses"
        await pilot.press("shift+tab")
        assert money.view.pane == "categories"


async def test_shift_tab_wraps_backwards(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        money = app.query_one("#money")
        await pilot.press("shift+tab")
        assert money.view.pane == "recurring"


# ── periods ──────────────────────────────────────────────────────────────
async def test_brackets_step_a_day_on_body_and_a_month_on_money(make_app):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await pilot.pause()
        await go_body(pilot, app)
        await pilot.press("left_square_bracket")
        assert app.query_one("#body").viewing_date == "2026-08-26"
        await go_money(pilot, app)
        await pilot.press("left_square_bracket")
        assert app.query_one("#money").view.anchor == "2026-07-27"


async def test_brackets_step_by_the_active_range(make_app):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        money = app.query_one("#money")
        await pilot.press("plus")  # 3m
        await pilot.press("left_square_bracket")
        assert money.view.anchor == "2026-05-27"


async def test_brackets_browse_reports_on_summary(make_app, db):
    upsert_report(db, date="2026-08-25", content="older")
    upsert_report(db, date="2026-08-26", content="newer")
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await pilot.press("1")
        await pilot.pause()
        await pilot.press("left_square_bracket")
        await pilot.pause()
        assert app.query_one("#summary").viewing_date == "2026-08-25"


# ── zoom ─────────────────────────────────────────────────────────────────
async def test_plus_widens_the_money_horizon_and_minus_narrows(make_app):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        money = app.query_one("#money")
        assert money.view.horizon == "MTD"
        await pilot.press("plus")
        assert money.view.horizon == "3m"
        await pilot.press("minus")
        assert money.view.horizon == "MTD"


async def test_plus_zooms_the_body_horizon_and_both_tabs_share_the_list(make_app):
    """The same horizon list serves Body and Money, so `+` means one thing."""
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        body = app.query_one("#body")
        assert body.horizon == "1m"
        await pilot.press("plus")
        assert body.horizon == "MTD"
        await pilot.press("minus")
        assert body.horizon == "1m"


# ── r means different things per tab ─────────────────────────────────────
async def test_r_rolls_on_money_and_regenerates_on_summary(make_app, db, type_into):
    from daybook.money import list_budget

    calls = []

    async def runner(system_prompt, user_prompt, *, timeout_sec, model=None):
        calls.append(1)
        return "generated"

    app = make_app(now=lambda: NOW, runner_text=runner)
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        await pilot.press("s")
        await type_into(pilot, "20.99 streaming !subscriptions")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        assert len(list_budget(db, month="2026-08")) == 1
        await go_day(pilot, app)
        await pilot.press("r")
        await pilot.pause()
        await pilot.pause()
    assert calls, "r on Summary should have regenerated"


# ── guards ───────────────────────────────────────────────────────────────
async def test_keys_are_inert_while_the_prompt_is_open(make_app):
    """`3`, deliberately — not the digit for the tab this test is already on.

    The test runs on Body, so pressing `2` here would leave the tab put whether
    show_scope's prompt guard works or not, and the assertion could not fail. `3`
    is the one digit that moves somewhere, so a tab that stays on Body is evidence
    of the guard rather than of arithmetic. Same for `t` and `w`: both do something
    on Body, so an open prompt swallowing them is observable.
    """
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await pilot.press("t")
        await pilot.press("3")
        assert app.active_tab_id == "tab-body"
        assert app.prompt.is_open is True


async def test_typing_a_refund_into_the_prompt_is_not_eaten_by_the_minus_key(
    make_app, db, type_into
):
    """`-` is bound to zoom-out. Textual routes printable keys to a focused
    Input, so a negative amount must still be typeable."""
    
    app = make_app()
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        await pilot.press("e")
        await type_into(pilot, "-24.99 refund grocery")
        assert app.prompt.value == "-24.99 refund grocery"
        await pilot.press("enter")
        await pilot.pause()
    assert all_expenses(db)[0]["amount"] == -24.99


async def test_escape_never_quits(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        for _ in range(4):
            await pilot.press("escape")
        await pilot.pause()
        assert app.is_running is True


async def test_g_with_a_bare_month_does_not_poison_the_tab(make_app):
    """Regression: `g 2026-06` on Body set viewing_date to "2026-06-30-01" — the
    month branch had started returning the month's last day, and two hand-cloned
    copies still appended `-01`. The next keypress then crashed the app."""
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("g")
        await pilot.pause()
        for ch in "2026-06":
            await pilot.press(ch if ch != "-" else "minus")
        await pilot.press("enter")
        await pilot.pause()
        viewing = app.query_one("#body").viewing_date
        prompt_open = app.prompt.is_open
        # Force a reload — this is where the poisoned value used to surface.
        await pilot.press("tab")
        await pilot.pause()
    assert viewing == "2026-06-30"
    assert prompt_open is False


async def test_all_three_tabs_resolve_g_the_same_way(make_app, db):
    """The rule lives in one function precisely so these cannot drift again.

    Day has to be seeded to take part at all: `SummaryTab.handle_prompt` refuses a
    date it has no report for, notifies, and leaves `viewing_date` alone — so
    without a report at the resolved date the tab would look like it disagreed with
    the other two about what `2026-06` means, when really it had declined to move.
    The second, newer report is what stops the Day leg being vacuous: the tab opens
    on the newest report, so `g` has to travel to reach June rather than being
    parked there already. That is asserted below, not assumed.
    """
    upsert_report(db, date="2026-06-30", content="june")
    upsert_report(db, date="2026-08-26", content="august")
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        assert app.query_one("#summary").viewing_date == "2026-08-26", (
            "Day did not open on the newest report, so its leg of this test proves nothing"
        )
        results = {}
        for key, tab_id in (("1", "#summary"), ("2", "#body"), ("3", "#money")):
            await pilot.press(key)
            await pilot.pause()
            await pilot.press("g")
            for ch in "2026-06":
                await pilot.press(ch if ch != "-" else "minus")
            await pilot.press("enter")
            await pilot.pause()
            tab = app.query_one(tab_id)
            results[tab_id] = getattr(tab, "viewing_date", None) or tab.view.anchor
    assert results["#summary"] == "2026-06-30"
    assert results["#body"] == "2026-06-30"
    assert results["#money"] == "2026-06-30"


async def test_a_bad_g_input_keeps_the_prompt_open(make_app):
    """HorizonError has to be in the app's RETRYABLE tuple or the prompt closes and
    the typed text is lost."""
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("g")
        await pilot.pause()
        for ch in "nope":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        still_open = app.prompt.is_open
        kept = app.prompt.value
        err = app.prompt.error
    assert still_open is True
    assert kept == "nope"
    assert "give a date like" in err


# ── left/right walk the tabs (#3) ────────────────────────────────────────
#
# A plain App binding, deliberately not `priority=True`. Measured on this Textual
# version: a `cursor_type="row"` DataTable does not claim left/right, so a plain
# binding fires with the table focused; and because it is plain, a focused Input
# still gets the keys first and keeps its cursor movement. A priority binding
# fires in both places — which reads as working right up until you try to edit a
# line you typed, and then the cursor will not move. That is the same trap
# recorded for printable keys in keymap.py.


async def test_right_walks_forward_through_the_tabs(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        assert app.scope == "body"
        await pilot.press("right")
        await pilot.pause()
        first = app.scope
        # Not just the pane switch. The arrows route through show_scope(), whose
        # other job is focusing the landed-on tab — set TabbedContent.active
        # directly instead and the scope is right while nothing is focused, so row
        # navigation and `enter` are dead until you press 1/2/3.
        focused = app.focused.id if app.focused else None
        await pilot.press("right")
        await pilot.pause()
        second = app.scope
    assert (first, second) == ("money", "money"), "right from money is clamped at the end"
    assert focused == "money-table", f"arrowing into Money left focus on {focused!r}"


async def test_left_walks_back_through_the_tabs(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        assert app.scope == "money"
        await pilot.press("left")
        await pilot.pause()
        first = app.scope
        await pilot.press("left")
        await pilot.pause()
        second = app.scope
    assert (first, second) == ("body", "summary")


async def test_walking_stops_at_both_ends(make_app, db):
    """Clamped, not wrapped — the same choice `[`/`]` already make at the ends of
    the data. `1` `2` `3` reach any tab in one keystroke, so wrapping would buy
    nothing and make it ambiguous where the arrow lands."""
    from textual.widgets import DataTable

    from daybook.body import add_food
    from daybook.money import add_expense

    # The cursor half of this test runs on Money — the right-hand end of the strip,
    # where the clamped `→` fires. Money opens on its categories pane, which shows
    # one row per category, so the categories have to differ: three expenses all
    # filed under "restaurant" collapse to a single row and `down` moves nothing.
    cats = ("restaurant", "grocery", "transport")
    for i in range(3):
        add_food(db, description=f"row{i}", kcal=100 + i, source="labeled",
                 date="2026-08-27", at=1787000000 + i * 3600)
        add_expense(db, amount=10.0 + i, description=f"expense{i}", category=cats[i],
                    date="2026-08-27")
    app = make_app(now=lambda: NOW.replace(tzinfo=None))
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        # Walk to the far end first, so this test cannot pass merely because the
        # keys are unbound — it has to see them working before it checks they stop.
        await pilot.press("right")
        await pilot.pause()
        assert app.scope == "money", f"the arrows did not walk at all: {app.scope}"
        await pilot.press("right")          # already on the last tab
        await pilot.pause()
        at_end = app.scope
        await pilot.press("left")
        await pilot.press("left")
        await pilot.pause()
        assert app.scope == "summary", f"the arrows did not walk back: {app.scope}"
        await pilot.press("left")           # already on the first tab
        await pilot.pause()
        at_start = app.scope
        # Seeded rows + a moved cursor, because "clamped" must mean "did nothing",
        # not "re-showed the tab you are on". Re-showing runs reload() ->
        # _fill_table -> table.clear(), which throws the cursor back to row 0 — the
        # same defect body_tab._set_estimating exists to avoid. Holding `→` at the
        # right end is exactly what a user does.
        await pilot.press("right")
        await pilot.press("right")
        await pilot.pause()
        assert app.scope == "money", "walked back to money for table test"
        table = app.query_one("#money-table", DataTable)
        table.focus()
        await pilot.press("down")
        await pilot.pause()
        cursor_before = table.cursor_row
        assert cursor_before > 0, "could not move the cursor — this would prove nothing"
        await pilot.press("right")          # already on the last tab
        await pilot.pause()
        cursor_after = table.cursor_row
    assert cursor_after == cursor_before, (
        f"a clamped arrow re-showed the tab and reset the cursor {cursor_before} -> {cursor_after}"
    )
    assert at_end == "money", f"right on the last tab moved to {at_end}"
    assert at_start == "summary", f"left on the first tab moved to {at_start}"


async def test_arrows_move_the_text_cursor_while_the_prompt_is_open(make_app, type_into):
    """The reason the binding must not be priority.

    A priority binding fires before the focused widget, so it would switch tabs
    while you were editing a line — and worse, swallow the key so the cursor never
    moved. Both halves are asserted: the tab must not change, and the cursor must.
    """
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await type_into(pilot, "78.2")
        await pilot.pause()
        before_pos, before_scope = app.prompt.cursor_position, app.scope
        await pilot.press("left")
        await pilot.press("left")
        await pilot.pause()
        after_pos, after_scope = app.prompt.cursor_position, app.scope
        assert app.prompt.is_open, "the prompt closed"
        value = app.prompt.value
    assert after_scope == before_scope == "body", (
        f"the prompt let a tab switch through: {after_scope}"
    )
    assert after_pos == before_pos - 2, (
        f"the arrows were stolen from the prompt: cursor {before_pos} -> {after_pos}"
    )
    assert value == "78.2", "the text changed"


async def test_the_arrow_order_matches_the_tab_pane_order(make_app):
    """Pins the coupling the arrows rely on.

    They step through `_TAB_OF`, whose insertion order has to agree with the
    TabPane order in `compose`. Nothing else forces those two to match, so a pane
    reordered without touching the dict would make the arrows walk sideways.
    """
    from textual.widgets import TabbedContent, TabPane

    from daybook.tui.app import _TAB_OF

    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        panes = [p.id for p in app.query_one("#tabs", TabbedContent).query(TabPane)]
    assert panes == list(_TAB_OF.values()), (
        f"tab panes are ordered {panes} but the arrows step {list(_TAB_OF.values())}"
    )


async def test_arrows_do_not_walk_tabs_behind_the_help_overlay(make_app):
    """`?` is a modal screen, and a tab switching behind it would be invisible
    until you closed it. A plain binding does not fire while a modal has focus,
    so this holds for free — and it is asserted because it stops holding the
    moment someone makes these keys priority."""
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        assert len(app.screen_stack) == 2, "the help overlay did not open"
        await pilot.press("right")
        await pilot.pause()
        scope, depth = app.scope, len(app.screen_stack)
    assert scope == "body", f"a tab switched behind the help overlay: {scope}"
    assert depth == 2, "the arrow dismissed the overlay"


async def test_arrows_still_walk_when_a_row_is_wider_than_the_table(make_app, db):
    """The measurement behind the plain binding only holds while the table fits.

    DataTable's left/right reach the App binding by raising SkipAction, and it
    raises that only when `allow_horizontal_scroll` is false — which flips true as
    soon as the content is wider than the viewport. Measured before the fix: at 80
    columns a 50-character description gives a virtual width of 84 against a 78-wide
    viewport, and `→` scrolled the table instead of changing tab, while the same data
    at 120 columns changed tab. A feature that works or not depending on window width
    and how long your description is, with no feedback either way.

    `overflow-x: hidden` in app.tcss keeps `allow_horizontal_scroll` false, so the
    fall-through is unconditional. This pins it at the narrow width the app declares
    it supports.
    """
    from daybook.money import add_expense

    long_desc = "a very long description that keeps going and going past any sane width"
    for i in range(4):
        add_expense(db, amount=10 + i, description=long_desc, category="restaurant",
                    date="2026-08-27")
    app = make_app(now=lambda: NOW.replace(tzinfo=None))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        await pilot.press("tab")            # categories -> the expense list
        await pilot.pause()
        assert app.query_one("#money").view.pane == "expenses", "not on the expense list"
        await pilot.press("left")
        await pilot.pause()
        forward = app.scope
        await pilot.press("right")
        await pilot.pause()
        back = app.scope
    assert forward == "body", f"a wide table swallowed the arrow: stayed on {forward}"
    assert back == "money", f"a wide table swallowed the arrow going back: {back}"
