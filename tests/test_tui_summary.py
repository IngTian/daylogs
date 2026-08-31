import datetime as dt
from zoneinfo import ZoneInfo

# This file used to carry its own `go_summary` that pressed "3" — the digit the
# Summary tab had before the Day tab took the lead. Every test here still passed,
# because pressing "3" lands on Money while `query_one("#summary")` returns the
# widget whatever tab is active; only the one test that presses a *key* noticed,
# and it hung forever waiting for a generate that `r` had rolled recurring
# instead. Aliasing the shared helper keeps one definition of where tab 1 is.
from helpers import go_day as go_summary

from daybook.summary import get_report, target_date, upsert_report

TZ = ZoneInfo("America/Toronto")
MORNING = dt.datetime(2026, 8, 27, 9, 0, tzinfo=TZ)


def _body(app):
    """The rendered markdown source, plus the empty-state line."""
    from textual.widgets import Markdown, Static
    md = app.query_one("#summary-body", Markdown)
    empty = app.query_one("#summary-empty", Static)
    return f"{md.source}\n{empty.content}"


async def test_shows_the_newest_report_on_open(make_app, db):
    upsert_report(db, date="2026-08-25", content="older")
    upsert_report(db, date="2026-08-26", content="## Body\n\nnewer")
    app = make_app()
    async with app.run_test() as pilot:
        tab = await go_summary(pilot, app)
        assert tab.viewing_date == "2026-08-26"
        assert "newer" in _body(app)


async def test_empty_state_when_no_reports(make_app, db):
    app = make_app()
    async with app.run_test() as pilot:
        tab = await go_summary(pilot, app)
        assert tab.viewing_date is None
        assert "press r" in _body(app)


async def test_g_generates_and_persists(make_app, db):
    async def runner(system_prompt, user_prompt, *, timeout_sec, model=None):
        return "## Body\n\nSteady."

    app = make_app(runner_text=runner)
    async with app.run_test() as pilot:
        await go_summary(pilot, app)
        await pilot.press("r")
        await pilot.pause()
        await pilot.pause()
        target = target_date(app.today())
    assert get_report(db, target)["content"].startswith("## Body")


async def test_generation_failure_surfaces_and_persists_nothing(make_app, db):
    from daybook.claude import ClaudeError

    async def runner(*a, **k):
        raise ClaudeError("down")

    app = make_app(runner_text=runner)
    async with app.run_test() as pilot:
        await go_summary(pilot, app)
        await pilot.press("r")
        await pilot.pause()
        await pilot.pause()
        target = target_date(app.today())
        assert app.is_running is True
    assert get_report(db, target) is None


async def test_bracket_keys_browse_earlier_reports(make_app, db):
    upsert_report(db, date="2026-08-25", content="older")
    upsert_report(db, date="2026-08-26", content="newer")
    app = make_app()
    async with app.run_test() as pilot:
        tab = await go_summary(pilot, app)
        await pilot.press("[")
        await pilot.pause()
        assert tab.viewing_date == "2026-08-25"
        await pilot.press("]")
        await pilot.pause()
        assert tab.viewing_date == "2026-08-26"


async def test_browsing_stops_at_the_oldest_report(make_app, db):
    upsert_report(db, date="2026-08-25", content="only")
    app = make_app()
    async with app.run_test() as pilot:
        tab = await go_summary(pilot, app)
        await pilot.press("[")
        await pilot.press("[")
        await pilot.pause()
        assert tab.viewing_date == "2026-08-25"
        assert "only" in _body(app)


async def test_browsing_stops_at_the_newest_report(make_app, db):
    upsert_report(db, date="2026-08-25", content="a")
    upsert_report(db, date="2026-08-26", content="b")
    app = make_app()
    async with app.run_test() as pilot:
        tab = await go_summary(pilot, app)
        await pilot.press("]")
        await pilot.pause()
        assert tab.viewing_date == "2026-08-26"


async def test_markup_tags_are_translated_not_shown_raw(make_app, db):
    upsert_report(db, date="2026-08-26", content="spent <num>$23.04</num>")
    app = make_app()
    async with app.run_test() as pilot:
        await go_summary(pilot, app)
        rendered = _body(app)
    assert "<num>" not in rendered
    assert "23.04" in rendered


async def test_header_shows_the_report_date_and_time(make_app, db):
    upsert_report(db, date="2026-08-26", content="x")
    app = make_app()
    async with app.run_test() as pilot:
        await go_summary(pilot, app)
        head = str(app.query_one("#summary-head").content)
    assert "Aug 26" in head
    assert "generated" in head


async def test_regenerating_replaces_the_viewed_day(make_app, db):
    upsert_report(db, date="2026-08-20", content="stale")

    async def runner(system_prompt, user_prompt, *, timeout_sec, model=None):
        assert '"target_date": "2026-08-20"' in user_prompt
        return "fresh"

    app = make_app(runner_text=runner)
    async with app.run_test() as pilot:
        await go_summary(pilot, app)
        await pilot.press("r")
        await pilot.pause()
        await pilot.pause()
    assert get_report(db, "2026-08-20")["content"] == "fresh"


async def test_autorun_fires_when_past_the_hour_and_no_report(make_app, db):
    calls = []

    async def runner(system_prompt, user_prompt, *, timeout_sec, model=None):
        calls.append(1)
        return "generated overnight"

    app = make_app(summary_after_hour=6, now=lambda: MORNING, runner_text=runner)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
    assert app.summary_worker_started is True
    assert len(calls) == 1
    assert get_report(db, "2026-08-26")["content"] == "generated overnight"


async def test_autorun_targets_yesterday_not_today(make_app, db):
    async def runner(system_prompt, user_prompt, *, timeout_sec, model=None):
        return "y"

    app = make_app(summary_after_hour=6, now=lambda: MORNING, runner_text=runner)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
    assert get_report(db, "2026-08-26") is not None
    assert get_report(db, "2026-08-27") is None


async def test_autorun_skipped_when_a_report_already_exists(make_app, db):
    upsert_report(db, date="2026-08-26", content="already there")
    calls = []

    async def runner(*a, **k):
        calls.append(1)
        return "should not run"

    app = make_app(summary_after_hour=6, now=lambda: MORNING, runner_text=runner)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
    assert app.summary_worker_started is False
    assert calls == []
    assert get_report(db, "2026-08-26")["content"] == "already there"


async def test_autorun_failure_does_not_break_the_app(make_app, db):
    from daybook.claude import ClaudeError

    async def runner(*a, **k):
        raise ClaudeError("offline")

    app = make_app(summary_after_hour=6, now=lambda: MORNING, runner_text=runner)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        assert app.is_running is True
    assert get_report(db, "2026-08-26") is None


async def test_a_superseded_generate_does_not_leave_the_header_stuck(make_app, db):
    """Why clearing `busy` outside a `finally` is correct here, not an oversight.

    `generate` is `@work(exclusive=True)`, so a second `r` cancels the first run, and
    a cancelled worker reaches neither the success nor the failure path —
    `CancelledError` is a BaseException that `except Exception` does not catch. That
    looks like a leak, and the tempting fix is a `finally`. It would be wrong: the
    cancellation only happens *because* a replacement is starting, and the
    replacement sets `busy` itself, so nothing is ever stuck. A `finally` would
    instead clear the flag in the gap between the two and blink the header off
    mid-generation.

    The estimate indicator in body_tab (#2) is built the same way for the same
    reason.
    """
    import asyncio

    upsert_report(db, date="2026-08-20", content="stale")
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def runner(system_prompt, user_prompt, *, timeout_sec, model=None):
        calls.append(user_prompt)
        if len(calls) == 1:
            await asyncio.sleep(3600)      # cancelled by the second press
        started.set()
        await release.wait()
        return "fresh"

    app = make_app(runner_text=runner)
    async with app.run_test() as pilot:
        await go_summary(pilot, app)
        tab = app.query_one("#summary")
        await pilot.press("r")
        await pilot.pause()
        await pilot.press("r")
        await started.wait()
        await pilot.pause()
        assert tab.busy, "the cancelled run cleared the flag while the second was in flight"
        release.set()
        await pilot.pause()
        await pilot.pause()
        assert not tab.busy, "busy outlived the generate that finished"
        assert "generating" not in tab.status_hint().lower(), tab.status_hint()


def _panel(app, which):
    from textual.widgets import Static

    return str(app.query_one(f"#day-{which}-body", Static).content)


async def test_the_body_panel_shows_weight_energy_and_meals(make_app, db):
    from daybook.body import add_food, add_weight

    add_weight(db, kg=71.2, date="2026-08-30", at=1788000000, note="")
    add_weight(db, kg=71.5, date="2026-08-24", at=1787400000, note="")
    add_food(db, description="eggs", kcal=400, source="labeled",
             date="2026-08-30", at=1788010000)
    add_food(db, description="salad", kcal=610, source="labeled",
             date="2026-08-30", at=1788020000)
    app = make_app(now=lambda: dt.datetime(2026, 8, 30, 9, 0, tzinfo=TZ))
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause()
        panel = _panel(app, "body")
    assert "71.2 kg" in panel
    assert "▼0.3" in panel, f"no 7-day delta: {panel!r}"
    assert "1,010" in panel, f"no intake total: {panel!r}"
    assert "2 meals" in panel


async def test_the_body_panel_names_the_key_when_there_is_no_weight(make_app, db):
    app = make_app(now=lambda: dt.datetime(2026, 8, 30, 9, 0, tzinfo=TZ))
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause()
        panel = _panel(app, "body")
    assert "0.0 kg" not in panel, "an absent weight must not render as zero"
    assert "press w" in panel, f"the empty state does not name its key: {panel!r}"


async def test_the_body_panel_names_the_key_when_there_is_no_profile(make_app, db):
    """No height/sex/birthday means no BMR, so intake has no baseline to sit against.
    The Body tab already answers this by naming `h`; so does this."""
    from daybook.body import add_food

    add_food(db, description="eggs", kcal=400, source="labeled",
             date="2026-08-30", at=1788010000)
    app = make_app(now=lambda: dt.datetime(2026, 8, 30, 9, 0, tzinfo=TZ))
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause()
        panel = _panel(app, "body")
    assert "press h" in panel, f"no BMR and no prompt to fix it: {panel!r}"
    assert "400" in panel, "intake should still show without a baseline"


async def test_the_body_panel_shows_net_against_bmr_when_the_profile_is_set(
    make_app, db, make_cfg
):
    from daybook.body import add_food, add_weight

    add_weight(db, kg=70.0, date="2026-08-30", at=1788000000, note="")
    add_food(db, description="eggs", kcal=2000, source="labeled",
             date="2026-08-30", at=1788010000)
    cfg = make_cfg(height_cm=180, sex="male", birthday="1990-01-01")
    app = make_app(cfg=cfg, now=lambda: dt.datetime(2026, 8, 30, 9, 0, tzinfo=TZ))
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause()
        panel = _panel(app, "body")
    assert "BMR" in panel
    assert "net" in panel


async def test_the_money_panel_shows_spend_burn_and_what_is_left(make_app, db):
    from daybook.money import add_expense, upsert_budget

    upsert_budget(db, month="2026-08", name="Grocery", category="grocery",
                  amount=500.0, source="manual")
    add_expense(db, amount=120.0, description="shop", category="grocery",
                date="2026-08-10")
    app = make_app(now=lambda: dt.datetime(2026, 8, 30, 9, 0, tzinfo=TZ))
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause()
        panel = _panel(app, "money")
    assert "120.00" in panel
    assert "500.00" in panel, f"the budget is not shown: {panel!r}"
    assert "380.00" in panel, f"what is left is not shown: {panel!r}"
    assert "30/31" in panel, f"the burn is not shown against elapsed days: {panel!r}"


async def test_the_money_panel_flags_an_overrun_with_the_glyph(make_app, db):
    """Colour is never the only signal in this app, so the glyph is asserted."""
    from daybook.money import add_expense, upsert_budget

    upsert_budget(db, month="2026-08", name="Grocery", category="grocery",
                  amount=100.0, source="manual")
    add_expense(db, amount=250.0, description="shop", category="grocery",
                date="2026-08-10")
    app = make_app(now=lambda: dt.datetime(2026, 8, 30, 9, 0, tzinfo=TZ))
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause()
        panel = _panel(app, "money")
    assert "⚠" in panel, f"an overrun with no glyph: {panel!r}"
    assert "grocery" in panel


async def test_the_money_panel_names_the_roll_key_when_no_budget_exists(make_app, db):
    """"0.00 budget" is true, useless, and reads as stale data. The Money tab's
    header already answers this by naming `r`; so does this."""
    from daybook.money import add_expense

    add_expense(db, amount=42.0, description="shop", category="grocery",
                date="2026-08-10")
    app = make_app(now=lambda: dt.datetime(2026, 8, 30, 9, 0, tzinfo=TZ))
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause()
        panel = _panel(app, "money")
    assert "42.00" in panel
    assert "press r" in panel, f"no budget and no prompt to fix it: {panel!r}"
    assert "0.00 of" not in panel, "an absent budget must not render as zero"
