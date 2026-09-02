import datetime as dt
from zoneinfo import ZoneInfo

# This file used to carry its own `go_summary` that pressed "3" — the digit the
# Summary tab had before the Day tab took the lead. Every test here still passed,
# because pressing "3" lands on Money while `query_one("#summary")` returns the
# widget whatever tab is active; only the one test that presses a *key* noticed,
# and it hung forever waiting for a generate that `r` had rolled recurring
# instead. Aliasing the shared helper keeps one definition of where tab 1 is.
from helpers import go_day as go_summary

from daylogs.summary import get_report, target_date, upsert_report

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
    from daylogs.claude import ClaudeError

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
    from daylogs.claude import ClaudeError

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
    from daylogs.body import add_food, add_weight

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
    The Body tab already answers this by naming `h`; so does this.

    The weight seed is load-bearing, not decoration: `body.compute_bmr` returns None
    on a missing weight *before* it consults the profile, so a seed with no weight
    passes this assertion with a complete profile too — covering nothing it names.
    With a weight logged, the absent profile is the only remaining cause.
    """
    from daylogs.body import add_food, add_weight

    add_weight(db, kg=70.0, date="2026-08-30", at=1788000000, note="")
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
    from daylogs.body import add_food, add_weight

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
    from daylogs.money import add_expense, upsert_budget

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
    from daylogs.money import add_expense, upsert_budget

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


async def test_the_money_panel_names_the_roll_key_when_recurring_items_exist(make_app, db):
    """"0.00 budget" is true, useless, and reads as stale data. When recurring
    items exist, name `r` which rolls them."""
    from daylogs.money import add_expense, upsert_recurring

    upsert_recurring(db, name="Internet", cost=50.0, cycle="monthly", category="grocery")
    add_expense(db, amount=42.0, description="shop", category="grocery",
                date="2026-08-10")
    app = make_app(now=lambda: dt.datetime(2026, 8, 30, 9, 0, tzinfo=TZ))
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause()
        panel = _panel(app, "money")
    assert "42.00" in panel
    assert "press r" in panel, f"recurring exists but r not named: {panel!r}"
    assert "1 to roll" in panel, f"count not shown: {panel!r}"
    assert "0.00 of" not in panel, "an absent budget must not render as zero"


async def test_the_money_panel_names_the_add_key_when_no_recurring_items_exist(make_app, db):
    """When no recurring items exist, `r` does nothing — name `b` which adds a line."""
    from daylogs.money import add_expense

    add_expense(db, amount=42.0, description="shop", category="grocery",
                date="2026-08-10")
    app = make_app(now=lambda: dt.datetime(2026, 8, 30, 9, 0, tzinfo=TZ))
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause()
        panel = _panel(app, "money")
    assert "42.00" in panel
    assert "press b" in panel, f"no recurring and b not named: {panel!r}"
    assert "press r" not in panel, f"no recurring but r named anyway: {panel!r}"


async def test_the_two_headers_name_their_own_dates(make_app, db):
    """The panels are today; the prose is the day it describes. Both said plainly."""
    from textual.widgets import Static

    from daylogs.body import add_weight

    add_weight(db, kg=71.0, date="2026-08-30", at=1788000000, note="")
    upsert_report(db, date="2026-08-29", content="yesterday's read")
    app = make_app(now=lambda: dt.datetime(2026, 8, 30, 9, 0, tzinfo=TZ))
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause()
        day = str(app.query_one("#day-head", Static).content)
        summ = str(app.query_one("#summary-head", Static).content)
    assert "Aug 30" in day, f"the TODAY header does not name today: {day!r}"
    assert "Aug 29" in summ, f"the SUMMARY header does not name its report: {summ!r}"
    assert "Aug 29" not in day and "Aug 30" not in summ, (
        f"the headers have blurred the two dates: {day!r} / {summ!r}"
    )


async def test_browsing_reports_leaves_the_panels_alone(make_app, db):
    """`[` moves the prose. The panels are "now" and do not travel."""
    from textual.widgets import Static

    from daylogs.body import add_weight

    add_weight(db, kg=71.0, date="2026-08-30", at=1788000000, note="")
    upsert_report(db, date="2026-08-29", content="newer")
    upsert_report(db, date="2026-08-28", content="older")
    app = make_app(now=lambda: dt.datetime(2026, 8, 30, 9, 0, tzinfo=TZ))
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause()
        before = _panel(app, "body")
        day_before = str(app.query_one("#day-head", Static).content)
        await pilot.press("left_square_bracket")
        await pilot.pause()
        summ = str(app.query_one("#summary-head", Static).content)
        after = _panel(app, "body")
        day_after = str(app.query_one("#day-head", Static).content)
    assert "Aug 28" in summ, f"browsing did not move the prose: {summ!r}"
    assert after == before, "browsing changed the panel values"
    assert day_after == day_before, "browsing changed the TODAY header"


async def test_generating_shows_on_the_summary_header_only(make_app, db):
    import asyncio

    from textual.widgets import Static

    started, release = asyncio.Event(), asyncio.Event()

    async def runner(system_prompt, user_prompt, *, timeout_sec, model=None):
        started.set()
        await release.wait()
        return "fresh"

    upsert_report(db, date="2026-08-29", content="old")
    app = make_app(runner_text=runner,
                   now=lambda: dt.datetime(2026, 8, 30, 9, 0, tzinfo=TZ))
    async with app.run_test(size=(120, 34)) as pilot:
        # Say which tab: `r` is "regenerate" only in the summary scope — on Money it
        # rolls recurring items, the generate never starts, and a bare
        # `started.wait()` then blocks forever instead of failing. Both halves of
        # that matter, so the wait is bounded as well.
        await go_summary(pilot, app)
        await pilot.press("r")
        await asyncio.wait_for(started.wait(), 5)
        await pilot.pause()
        day = str(app.query_one("#day-head", Static).content)
        summ = str(app.query_one("#summary-head", Static).content)
        release.set()
        await pilot.pause()
        await pilot.pause()
        after = str(app.query_one("#summary-head", Static).content)
    assert "generating" in summ.lower(), f"no progress on the summary header: {summ!r}"
    assert "generating" not in day.lower(), (
        f"the TODAY header claims to be generating, but the figures are not: {day!r}"
    )
    assert "generating" not in after.lower(), "the indicator outlived the run"


async def test_the_panels_do_not_clip_or_wrap_at_eighty_columns(make_app, db):
    """The app declares support down to 80 columns, where the two panels stack."""
    from daylogs.body import add_weight
    from daylogs.money import add_expense, upsert_recurring

    add_weight(db, kg=71.2, date="2026-08-30", at=1788000000, note="")
    upsert_recurring(db, name="Internet", cost=50.0, cycle="monthly", category="grocery")
    add_expense(db, amount=1284.5, description="shop", category="grocery",
                date="2026-08-10")
    app = make_app(now=lambda: dt.datetime(2026, 8, 30, 9, 0, tzinfo=TZ))
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        body_panel = _panel(app, "body")
        money_panel = _panel(app, "money")
    assert "71.2 kg" in body_panel, f"clipped at 80 columns: {body_panel!r}"
    assert "1,284.50" in money_panel, f"clipped at 80 columns: {money_panel!r}"
    for line in (body_panel + "\n" + money_panel).splitlines():
        assert len(line) <= 76, f"line too wide for a stacked panel: {line!r}"

# ── colour on the Day tab ────────────────────────────────────────────────
# The palette reached Body and Money but not the tab the app opens to, so the
# landing screen showed the same facts in plain white. These assert on the
# individual line rather than the whole panel: a test that only asks "is GOOD
# anywhere in this panel" passes on a neighbouring line's colour.


def _line(panel: str, needle: str) -> str:
    for line in panel.splitlines():
        if needle in line:
            return line
    raise AssertionError(f"no {needle!r} line in panel:\n{panel}")


async def test_the_body_panel_colours_the_weight_trend_by_direction(make_app, db):
    """Down is good — the same assumption the Body tab already makes, and the
    arrow carries the direction regardless, so colour stays emphasis."""
    from daylogs.body import add_weight
    from daylogs.tui.widgets import BAD, GOOD

    add_weight(db, kg=71.5, date="2026-08-24", at=1787400000, note="")
    add_weight(db, kg=71.2, date="2026-08-30", at=1788000000, note="")
    app = make_app(now=lambda: dt.datetime(2026, 8, 30, 9, 0, tzinfo=TZ))
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause()
        line = _line(_panel(app, "body"), "weight")
    assert GOOD in line, f"a falling weight is not green: {line!r}"
    assert BAD not in line


async def test_a_rising_weight_is_red_on_the_day_panel(make_app, db):
    from daylogs.body import add_weight
    from daylogs.tui.widgets import BAD, GOOD

    add_weight(db, kg=71.2, date="2026-08-24", at=1787400000, note="")
    add_weight(db, kg=71.9, date="2026-08-30", at=1788000000, note="")
    app = make_app(now=lambda: dt.datetime(2026, 8, 30, 9, 0, tzinfo=TZ))
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause()
        line = _line(_panel(app, "body"), "weight")
    assert BAD in line, f"a rising weight is not red: {line!r}"
    assert GOOD not in line


async def test_the_body_panel_colours_net_by_direction(make_app, db, make_cfg):
    """A deficit is green on the same reasoning as a falling weight, and the sign
    on the number is the signal colour only emphasises."""
    from daylogs.body import add_food, add_weight
    from daylogs.tui.widgets import GOOD

    add_weight(db, kg=70.0, date="2026-08-30", at=1788000000, note="")
    add_food(db, description="eggs", kcal=400, source="labeled",
             date="2026-08-30", at=1788010000)
    cfg = make_cfg(height_cm=180, sex="male", birthday="1990-01-01")
    app = make_app(cfg=cfg, now=lambda: dt.datetime(2026, 8, 30, 9, 0, tzinfo=TZ))
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause()
        line = _line(_panel(app, "body"), "net")
    assert GOOD in line, f"400 kcal against maintenance is not a green net: {line!r}"


async def test_a_surplus_net_is_red_on_the_day_panel(make_app, db, make_cfg):
    from daylogs.body import add_food, add_weight
    from daylogs.tui.widgets import BAD

    add_weight(db, kg=70.0, date="2026-08-30", at=1788000000, note="")
    add_food(db, description="feast", kcal=4000, source="labeled",
             date="2026-08-30", at=1788010000)
    cfg = make_cfg(height_cm=180, sex="male", birthday="1990-01-01")
    app = make_app(cfg=cfg, now=lambda: dt.datetime(2026, 8, 30, 9, 0, tzinfo=TZ))
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause()
        line = _line(_panel(app, "body"), "net")
    assert BAD in line, f"4,000 kcal against maintenance is not a red net: {line!r}"


async def test_the_money_panel_colours_what_is_left(make_app, db):
    """Money's own header already paints what is left green; the Day panel showing
    the same figure in white was the inconsistency."""
    from daylogs.money import add_expense, upsert_budget
    from daylogs.tui.widgets import GOOD

    upsert_budget(db, month="2026-08", name="Grocery", category="grocery",
                  amount=500.0, source="manual")
    add_expense(db, amount=120.0, description="shop", category="grocery",
                date="2026-08-10")
    app = make_app(now=lambda: dt.datetime(2026, 8, 30, 9, 0, tzinfo=TZ))
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause()
        line = _line(_panel(app, "money"), "left")
    assert GOOD in line, f"money left over is not green: {line!r}"


async def test_an_overrun_is_red_on_both_lines_of_the_money_panel(make_app, db):
    """The glyph is still asserted separately: colour is never the only signal."""
    from daylogs.money import add_expense, upsert_budget
    from daylogs.tui.widgets import BAD

    upsert_budget(db, month="2026-08", name="Grocery", category="grocery",
                  amount=100.0, source="manual")
    add_expense(db, amount=250.0, description="shop", category="grocery",
                date="2026-08-10")
    app = make_app(now=lambda: dt.datetime(2026, 8, 30, 9, 0, tzinfo=TZ))
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause()
        panel = _panel(app, "money")
    assert BAD in _line(panel, "left"), "a negative remainder is not red"
    assert BAD in _line(panel, "over"), "the overrun line is not red"
    assert "⚠" in panel, "colour must not have replaced the glyph"


async def test_burn_is_amber_only_when_it_runs_ahead_of_the_month(make_app, db):
    """84% spent on day 27 of 31 is fine and the same number on day 12 is not, so
    the warning is against elapsed days rather than against a flat threshold."""
    from daylogs.money import add_expense, upsert_budget
    from daylogs.tui.widgets import WARN

    # Day 30 of 31 is ~97% elapsed. 99 of 100 spent is ahead of that, and still
    # under budget — so this is the warning state, not the overrun state.
    upsert_budget(db, month="2026-08", name="Grocery", category="grocery",
                  amount=100.0, source="manual")
    add_expense(db, amount=99.0, description="shop", category="grocery",
                date="2026-08-10")
    app = make_app(now=lambda: dt.datetime(2026, 8, 30, 9, 0, tzinfo=TZ))
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause()
        line = _line(_panel(app, "money"), "burn")
    assert WARN in line, f"spending ahead of the month is not flagged: {line!r}"


async def test_burn_is_plain_when_spending_is_behind_the_month(make_app, db):
    from daylogs.money import add_expense, upsert_budget
    from daylogs.tui.widgets import WARN

    upsert_budget(db, month="2026-08", name="Grocery", category="grocery",
                  amount=500.0, source="manual")
    add_expense(db, amount=120.0, description="shop", category="grocery",
                date="2026-08-10")
    app = make_app(now=lambda: dt.datetime(2026, 8, 30, 9, 0, tzinfo=TZ))
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause()
        line = _line(_panel(app, "money"), "burn")
    assert WARN not in line, f"24% spent on day 30 must not warn: {line!r}"
