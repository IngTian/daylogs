import datetime as dt
from zoneinfo import ZoneInfo

from helpers import go_body

TZ = ZoneInfo("America/Toronto")


async def test_prompt_opens_and_escape_closes_it(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        assert app.prompt.is_open is True
        await pilot.press("escape")
        await pilot.pause()
        assert app.prompt.is_open is False


async def test_tab_keys_are_inert_while_the_prompt_is_open(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await pilot.press("2")
        assert app.active_tab_id == "tab-body"
        assert app.prompt.value == "2"


async def test_q_does_not_quit_while_the_prompt_is_open(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await pilot.press("q")
        await pilot.pause()
        assert app.is_running is True
        assert app.prompt.value == "q"


async def test_prompt_history_recalls_last_entry(make_app, type_into):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await type_into(pilot, "78.2")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("w")
        await pilot.press("up")
        assert app.prompt.value == "78.2"


async def test_prompt_history_is_per_label(make_app, type_into):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await type_into(pilot, "78.2")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("f")
        await pilot.press("up")
        assert app.prompt.value == ""


async def test_empty_submission_is_a_no_op(make_app, db):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open is False
    assert db.execute("SELECT count(*) FROM weight").fetchone()[0] == 0


async def test_q_quits(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("q")
        await pilot.pause()
    assert app.is_running is False


async def test_undo_with_nothing_to_undo_does_not_crash(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("u")
        await pilot.pause()
        assert app.is_running is True


async def test_autorun_skipped_before_configured_hour(make_app):
    app = make_app(
        summary_after_hour=23,
        now=lambda: dt.datetime(2026, 8, 27, 9, 0, tzinfo=TZ),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.summary_worker_started is False


async def test_subtitle_shows_the_injected_date(make_app):
    app = make_app(now=lambda: dt.datetime(2026, 8, 27, 9, 0, tzinfo=TZ))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "Aug 27" in app.sub_title


async def test_the_app_opens_on_the_day_tab(make_app):
    """Tab 1 is what you see on launch — the whole reason the dashboard moved."""
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.scope == "summary"


async def test_the_digit_keys_match_the_visible_tab_numbers(make_app):
    """The labels say 1 Day / 2 Body / 3 Money, so the digits must agree. They are
    bound to named actions rather than positions, so reordering the panes alone
    would leave `2` jumping to a tab labelled 3."""
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        seen = {}
        for digit in ("2", "3", "1"):
            await pilot.press(digit)
            await pilot.pause()
            seen[digit] = app.scope
    assert seen == {"1": "summary", "2": "body", "3": "money"}


async def test_the_pane_labels_are_numbered_in_order(make_app):
    from textual.widgets import TabbedContent, TabPane

    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        tabs_widget = app.query_one("#tabs", TabbedContent)
        panes = tabs_widget.query(TabPane)
        labels = [str(tabs_widget.get_tab(p.id).label) for p in panes]
    assert labels == ["1 Day", "2 Body", "3 Money"]
