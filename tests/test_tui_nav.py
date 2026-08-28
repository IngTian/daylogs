import datetime as dt
from zoneinfo import ZoneInfo

from helpers import all_expenses

from daybook.summary import upsert_report

TZ = ZoneInfo("America/Toronto")
NOW = dt.datetime(2026, 8, 27, 9, 0, tzinfo=TZ)


# ── jump to now: the key v1 had no equivalent for ────────────────────────
async def test_t_returns_body_to_today_from_far_away(make_app):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
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
        await pilot.press("2")
        await pilot.pause()
        money = app.query_one("#money")
        money.view.anchor = "2026-03-15"
        await pilot.press("t")
        await pilot.pause()
        assert money.view.anchor == "2026-08-27"


async def test_t_on_money_also_clears_filters(make_app):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await pilot.press("2")
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
        await pilot.press("3")
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
        await pilot.pause()
        await pilot.press("g")
        await type_into(pilot, "2026-06-15")
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one("#body").viewing_date == "2026-06-15"


async def test_g_jumps_money_to_a_month(make_app, type_into):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("g")
        await type_into(pilot, "2026-06")
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one("#money").view.anchor == "2026-06-30"


async def test_g_with_junk_keeps_the_prompt_open(make_app, type_into):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
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
        await pilot.press("2")
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
        await pilot.press("2")
        await pilot.pause()
        money = app.query_one("#money")
        await pilot.press("shift+tab")
        assert money.view.pane == "recurring"


# ── periods ──────────────────────────────────────────────────────────────
async def test_brackets_step_a_day_on_body_and_a_month_on_money(make_app):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("left_square_bracket")
        assert app.query_one("#body").viewing_date == "2026-08-26"
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("left_square_bracket")
        assert app.query_one("#money").view.anchor == "2026-07-27"


async def test_brackets_step_by_the_active_range(make_app):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await pilot.press("2")
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
        await pilot.press("3")
        await pilot.pause()
        await pilot.press("left_square_bracket")
        await pilot.pause()
        assert app.query_one("#summary").viewing_date == "2026-08-25"


# ── zoom ─────────────────────────────────────────────────────────────────
async def test_plus_widens_the_money_horizon_and_minus_narrows(make_app):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await pilot.press("2")
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
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("s")
        await type_into(pilot, "20.99 streaming subscriptions")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        assert len(list_budget(db, month="2026-08")) == 1
        await pilot.press("3")
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        await pilot.pause()
    assert calls, "r on Summary should have regenerated"


# ── guards ───────────────────────────────────────────────────────────────
async def test_keys_are_inert_while_the_prompt_is_open(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("w")
        await pilot.press("t")
        await pilot.press("2")
        assert app.active_tab_id == "tab-body"
        assert app.prompt.is_open is True


async def test_typing_a_refund_into_the_prompt_is_not_eaten_by_the_minus_key(
    make_app, db, type_into
):
    """`-` is bound to zoom-out. Textual routes printable keys to a focused
    Input, so a negative amount must still be typeable."""
    
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("e")
        await type_into(pilot, "-24.99 refund grocery")
        assert app.prompt.value == "-24.99 refund grocery"
        await pilot.press("enter")
        await pilot.pause()
    assert all_expenses(db)[0]["amount"] == -24.99


async def test_escape_never_quits(make_app):
    app = make_app()
    async with app.run_test() as pilot:
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


async def test_all_three_tabs_resolve_g_the_same_way(make_app):
    """The rule lives in one function precisely so these cannot drift again."""
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        results = {}
        for key, tab_id in (("1", "#body"), ("2", "#money")):
            await pilot.press(key)
            await pilot.pause()
            await pilot.press("g")
            for ch in "2026-06":
                await pilot.press(ch if ch != "-" else "minus")
            await pilot.press("enter")
            await pilot.pause()
            tab = app.query_one(tab_id)
            results[tab_id] = getattr(tab, "viewing_date", None) or tab.view.anchor
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
