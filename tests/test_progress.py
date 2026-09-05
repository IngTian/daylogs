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
        for _ in range(6):
            await pilot.pause()
        after = _shown(app)
    assert len(both.splitlines()) == 2, f"one call hid the other: {both!r}"
    assert "calories" in both and "activity factor" in both, both
    # Both keys have to be released, not just the one whose worker happened to finish last.
    assert after == "", f"a line outlived its call: {after!r}"


# ── the other half of "switch tabs while you wait" ───────────────────────
# The popup makes waiting-while-you-work the advertised flow (README: "switching tabs
# while you wait doesn't hide it"). So the answer has to survive the switch too: a
# worker-opened `confirm food` / `confirm activity` prompt used to be handed to whichever
# tab was active when it arrived, and SummaryTab/MoneyTab have no branch for those labels
# and no `else` — so `enter` fell through, closed the prompt, and wrote nothing. No toast,
# no row, and no way back, because `show_scope` returns early while a prompt is open.


async def _gated(app, pilot, monkeypatch, key: str, line: str, attr: str, value):
    started, release = asyncio.Event(), asyncio.Event()

    async def gate(**kw):
        started.set()
        await release.wait()
        return value

    monkeypatch.setattr(f"daylogs.tui.body_tab.estimate.{attr}", gate)
    await go_body(pilot, app)
    await pilot.press(key)
    for ch in line:
        await pilot.press("space" if ch == " " else ch)
    await pilot.press("enter")
    await asyncio.wait_for(started.wait(), 5)
    return release


async def test_a_food_estimate_accepted_from_another_tab_still_writes_the_row(
    make_app, db, monkeypatch
):
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        release = await _gated(
            app, pilot, monkeypatch, "f", "mystery stew", "from_text",
            Estimate(description="stew", kcal=500),
        )
        await pilot.press("3")                 # wander off while it runs
        await pilot.pause()
        assert app.scope == "money"
        release.set()
        await pilot.pause()
        await pilot.pause()
        assert app.prompt.label == "confirm food"
        await pilot.press("enter")
        await pilot.pause()
    rows = list(db.execute("SELECT * FROM food"))
    assert len(rows) == 1, "the meal was silently discarded"
    assert rows[0]["kcal"] == 500


async def test_an_activity_inference_accepted_from_another_tab_still_writes_the_row(
    make_app, db, monkeypatch
):
    """The one CLAUDE.md is most explicit about: "the description is the user's data and
    the multiplier is a guess; losing the first because the second failed is the worse
    outcome". Losing it because the user looked at another tab is worse still — and a day
    with no activity row silently takes the profile baseline, rebasing every calorie
    figure for that day."""
    from daylogs.estimate import Effort

    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        release = await _gated(
            app, pilot, monkeypatch, "a", "gym 1h", "factor_from_text", Effort(factor=1.6),
        )
        await pilot.press("1")
        await pilot.pause()
        assert app.scope == "summary"
        release.set()
        await pilot.pause()
        await pilot.pause()
        assert app.prompt.label == "confirm activity"
        await pilot.press("enter")
        await pilot.pause()
    rows = list(db.execute("SELECT * FROM activity"))
    assert len(rows) == 1, "the logged activity vanished"
    assert rows[0]["factor"] == 1.6


async def test_escaping_a_confirm_prompt_from_another_tab_disarms_the_right_tab(
    make_app, db, monkeypatch
):
    """The cancel path routes by owner too. Otherwise BodyTab keeps `_pending` armed and
    the next plain `f` silently inherits the abandoned estimate's calories."""
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        release = await _gated(
            app, pilot, monkeypatch, "f", "mystery stew", "from_text",
            Estimate(description="stew", kcal=500),
        )
        await pilot.press("3")
        await pilot.pause()
        release.set()
        await pilot.pause()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.query_one("#body")._pending is None, "the abandoned estimate stayed armed"


async def test_the_summarys_popup_clock_restarts_on_a_retry(make_app, db, monkeypatch):
    """`summary.generate` allows one retry, and each attempt gets the FULL
    `summary_timeout_sec`. The popup began once, so a first attempt that used its whole
    budget left the second rendering `121s / 120s` … `240s / 120s` — a number that is
    neither the job's budget nor the running call's elapsed, against a bar that says 120.

    The clock therefore restarts per attempt rather than the label widening.
    """
    clock = [1000.0]
    calls = []
    started, release = asyncio.Event(), asyncio.Event()

    async def flaky(system_prompt, user_prompt, *, timeout_sec, model=None):
        calls.append(1)
        if len(calls) == 1:
            clock[0] += 200.0          # the first attempt burns more than the budget
            raise RuntimeError("claude fell over")
        started.set()
        await release.wait()           # hold the second attempt open to be looked at
        return "# fresh\n\nbody"

    app = make_app(runner_text=flaky, now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        app.query_one(WorkPopup)._clock = lambda: clock[0]
        await go_day(pilot, app)
        await pilot.press("r")
        await asyncio.wait_for(started.wait(), 5)
        await pilot.pause()
        # Paint at the instant the second attempt is running.
        app.query_one(WorkPopup)._repaint()
        mid = _shown(app)
        release.set()
        for _ in range(6):
            await pilot.pause()
    assert len(calls) == 2, f"the retry never happened: {calls}"
    # Parsed, not matched as a substring: `"0s / 120s" in "200s / 120s"` is TRUE, so the
    # obvious assertion passes on exactly the output it is meant to reject. Fifth time this
    # class of mistake has bitten in this feature's history — see the sibling tests.
    import re

    m = re.search(r"(\d+)s / (\d+)s", mid)
    assert m, f"no elapsed/budget pair in the popup: {mid!r}"
    elapsed, budget = int(m.group(1)), int(m.group(2))
    assert budget == 120, f"the popup is showing the wrong budget: {mid!r}"
    assert elapsed < 5, f"the clock carried the failed attempt's time over: {mid!r}"
