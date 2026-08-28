import datetime as dt
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Toronto")


async def test_starts_on_body_tab(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.active_tab_id == "tab-body"


async def test_number_keys_switch_tabs(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("2")
        assert app.active_tab_id == "tab-money"
        await pilot.press("3")
        assert app.active_tab_id == "tab-summary"
        await pilot.press("1")
        assert app.active_tab_id == "tab-body"


async def test_prompt_opens_and_escape_closes_it(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("w")
        assert app.prompt.is_open is True
        await pilot.press("escape")
        await pilot.pause()
        assert app.prompt.is_open is False


async def test_tab_keys_are_inert_while_the_prompt_is_open(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("w")
        await pilot.press("2")
        assert app.active_tab_id == "tab-body"
        assert app.prompt.value == "2"


async def test_q_does_not_quit_while_the_prompt_is_open(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("w")
        await pilot.press("q")
        await pilot.pause()
        assert app.is_running is True
        assert app.prompt.value == "q"


async def test_prompt_history_recalls_last_entry(make_app, type_into):
    app = make_app()
    async with app.run_test() as pilot:
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
