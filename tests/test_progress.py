"""The in-progress popup.

The indicator's *lifetime* was already right — a suffix on the FOOD and SUMMARY headers
for exactly as long as a call ran, which is what replaced a 3-second toast fired against
a 60-second call. Its *location* was not: it lived on the tab that started the work, so
pressing `3` erased every trace of a running estimate and the answer arrived later as a
prompt with no explanation.

The existing exit-path tests moved with it (see `test_tui_body.py` — success, failure,
timeout, a cancelled worker, the photo path). What is here is what the popup adds: the
formatting, the keying that lets two calls run at once, and being visible from any tab.
"""

import asyncio
import datetime as dt

from helpers import go_body, go_day, go_money

from daylogs.estimate import Estimate
from daylogs.tui.progress import Job, WorkPopup, render_jobs

NOW = dt.datetime(2026, 8, 28, 9, 0)


def _job(key="food", label="estimating calories", started=100.0, timeout_sec=60):
    return Job(key=key, label=label, started=started, timeout_sec=timeout_sec)


# ── the pure renderer ────────────────────────────────────────────────────
def test_nothing_running_renders_nothing():
    assert render_jobs((), now=100.0) == ""


def test_a_job_names_itself_and_its_elapsed_time():
    out = render_jobs((_job(),), now=118.0)
    assert "estimating calories" in out
    assert "18s" in out


def test_elapsed_is_shown_against_the_budget_the_call_is_allowed():
    """The number that makes a static line informative with animations off: it says both
    that the call is still alive and roughly how much patience is left."""
    assert "18s / 60s" in render_jobs((_job(),), now=118.0)
    assert "18s / 120s" in render_jobs((_job(timeout_sec=120),), now=118.0)


def test_elapsed_is_whole_seconds():
    assert "18s" in render_jobs((_job(),), now=118.9)


def test_a_now_before_the_start_reads_zero_rather_than_going_negative():
    """A full second backwards, not a fraction: `int()` truncates toward zero, so
    `now=99.999` against `started=100.0` is already "0s" and proves nothing about the
    clamp — which is how this test passed while the clamp was removed.

    The clamp is about `render_jobs`' own contract rather than about clocks. It is a pure
    function whose `now` is an argument, and "-3s / 60s" is the kind of output that makes
    a reader distrust the whole panel.

    Asserted as `"0s / 60s"`, not `"0s"`: the *budget* ends in "0s", so the loose version
    matched "-1s / 60s" and let the clamp be deleted with the suite still green.
    """
    assert "0s / 60s" in render_jobs((_job(),), now=99.0)


def test_past_the_budget_it_keeps_counting_honestly():
    """The call is about to be killed by its own timeout. Freezing the display at the
    budget would hide the one moment the number matters."""
    assert "64s / 60s" in render_jobs((_job(),), now=164.0)


def test_two_jobs_are_two_lines():
    """A food estimate and the daily read can genuinely overlap, and so can a food
    estimate and an activity inference — they have separate worker groups on purpose."""
    out = render_jobs((_job(), _job(key="summary", label="writing the daily read")), now=110.0)
    assert len(out.splitlines()) == 2
    assert "estimating calories" in out and "writing the daily read" in out


def test_a_label_with_markup_in_it_is_escaped():
    """Labels are literals today. This is what keeps that from being load-bearing — the
    same reason `widgets.esc` exists."""
    assert "\\[" in render_jobs((_job(label="doing [b]things[/b]"),), now=100.0)


# ── the widget ───────────────────────────────────────────────────────────
def test_a_fresh_popup_is_hidden():
    assert WorkPopup().display is False


def test_beginning_and_ending_shows_and_hides():
    p = WorkPopup(clock=lambda: 100.0)
    p.begin("food", "estimating calories", 60)
    assert p.display is True
    p.end("food")
    assert p.display is False


def test_ending_one_job_leaves_the_other_showing():
    """Why the popup is keyed rather than a counter or a flag: the two calls carry
    different words, and finishing one must not blank the other's line."""
    p = WorkPopup(clock=lambda: 100.0)
    p.begin("food", "estimating calories", 60)
    p.begin("summary", "writing the daily read", 120)
    p.end("food")
    assert p.display is True
    assert "daily read" in str(p.render())
    assert "estimating calories" not in str(p.render())


def test_ending_a_job_that_was_never_begun_is_not_an_error():
    """A worker that failed and one that was cancelled both reach `end`, sometimes for a
    key the replacement has already taken over."""
    WorkPopup().end("food")


def test_beginning_the_same_key_again_restarts_its_clock():
    """A superseded estimate should show the second call's elapsed time, not the first's —
    and must not add a second line for the same job."""
    t = [100.0]
    p = WorkPopup(clock=lambda: t[0])
    p.begin("food", "estimating calories", 60)
    t[0] = 130.0
    p.begin("food", "estimating calories", 60)
    t[0] = 140.0
    p._repaint()          # what the timer does; `render()` returns the last paint
    out = str(p.render())
    assert len(out.splitlines()) == 1
    assert "10s" in out, out


# ── in the app ───────────────────────────────────────────────────────────
def _shown(app) -> str:
    p = app.query_one(WorkPopup)
    return str(p.render()) if p.display else ""


async def test_the_popup_is_absent_from_an_idle_app(make_app, db):
    """It costs no rows when nothing is running, so an idle screen is unchanged — which
    is why it can sit in the bottom container instead of floating over the content."""
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        assert app.query_one(WorkPopup).display is False
        assert _shown(app) == ""


async def test_a_running_estimate_is_visible_from_another_tab(make_app, db, type_into, monkeypatch):
    """The reason it moved. Press `f`, then `3`, and the old indicator was gone entirely:
    it was a suffix on BodyTab's own header and in BodyTab's own footer hint."""
    started, release = asyncio.Event(), asyncio.Event()

    async def gated(**kw):
        started.set()
        await release.wait()
        return Estimate(description="gated meal", kcal=500)

    monkeypatch.setattr("daylogs.tui.body_tab.estimate.from_text", gated)
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        await go_body(pilot, app)
        await pilot.press("f")
        await type_into(pilot, "mystery stew")
        await pilot.press("enter")
        await asyncio.wait_for(started.wait(), 5)
        await pilot.pause()
        on_money = await go_money(pilot, app) and _shown(app)
        on_day = await go_day(pilot, app) and _shown(app)
        release.set()
        await pilot.pause()
        await pilot.pause()
        after = _shown(app)
    assert "estimating" in on_money.lower(), f"the Money tab hides the running call: {on_money!r}"
    assert "estimating" in on_day.lower(), f"the Day tab hides the running call: {on_day!r}"
    assert after == "", f"the popup outlived the call: {after!r}"


async def test_the_popup_ticks_while_a_call_is_in_flight(make_app, db, type_into, monkeypatch):
    """With animations off a static word cannot say "still alive". The elapsed figure is
    what does, so it has to actually advance — the timer is the point, not decoration.

    Drives the popup's injected clock rather than sleeping: a test that waits a real
    second to prove a second passed is a test that makes the suite slower every time
    someone adds one.
    """
    started, release = asyncio.Event(), asyncio.Event()

    async def gated(**kw):
        started.set()
        await release.wait()
        return Estimate(description="gated meal", kcal=500)

    monkeypatch.setattr("daylogs.tui.body_tab.estimate.from_text", gated)
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        clock = [1000.0]
        app.query_one(WorkPopup)._clock = lambda: clock[0]
        await go_body(pilot, app)
        await pilot.press("f")
        await type_into(pilot, "mystery stew")
        await pilot.press("enter")
        await asyncio.wait_for(started.wait(), 5)
        await pilot.pause()
        first = _shown(app)
        # The timer is the mechanism, so it is asserted directly. Driving `_repaint`
        # alone passed with `set_interval` deleted — the popup would have frozen at 0s
        # for the whole call and nothing would have noticed.
        ticking = app.query_one(WorkPopup)._timer
        clock[0] += 7.0
        app.query_one(WorkPopup)._repaint()
        await pilot.pause()
        later = _shown(app)
        release.set()
        await pilot.pause()
        await pilot.pause()
        stopped = app.query_one(WorkPopup)._timer
    assert "0s /" in first, first
    assert "7s /" in later, later
    assert ticking is not None, "nothing repaints the popup, so the figure never moves"
    assert stopped is None, "the timer outlived the work it was counting"


async def test_two_calls_at_once_show_two_lines(make_app, db, type_into, monkeypatch):
    """A gym session and a meal estimate have separate worker groups precisely so one
    does not cancel the other, so the popup has to be able to say both are running."""
    food_started, activity_started = asyncio.Event(), asyncio.Event()
    release = asyncio.Event()

    async def gated_food(**kw):
        food_started.set()
        await release.wait()
        return Estimate(description="stew", kcal=500)

    async def gated_activity(**kw):
        activity_started.set()
        await release.wait()
        from daylogs.estimate import Effort

        return Effort(description="gym", factor=1.5)

    monkeypatch.setattr("daylogs.tui.body_tab.estimate.from_text", gated_food)
    monkeypatch.setattr("daylogs.tui.body_tab.estimate.factor_from_text", gated_activity)
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        await go_body(pilot, app)
        await pilot.press("f")
        await type_into(pilot, "mystery stew")
        await pilot.press("enter")
        await asyncio.wait_for(food_started.wait(), 5)
        await pilot.press("a")
        await type_into(pilot, "gym 1h")
        await pilot.press("enter")
        await asyncio.wait_for(activity_started.wait(), 5)
        await pilot.pause()
        both = _shown(app)
        release.set()
        await pilot.pause()
        await pilot.pause()
    assert len(both.splitlines()) == 2, f"one call hid the other: {both!r}"
    assert "calories" in both and "activity factor" in both, both
