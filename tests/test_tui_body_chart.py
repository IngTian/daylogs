import datetime as dt
from zoneinfo import ZoneInfo

from daybook.body import add_food, add_weight

TZ = ZoneInfo("America/Toronto")
NOW = dt.datetime(2026, 8, 27, 9, 0, tzinfo=TZ)


def _seed(db, n=40):
    for i in range(n):
        day = f"2026-07-{i % 28 + 1:02d}"
        add_weight(db, kg=80.0 - i * 0.05, date=day, at=1000 + i)


def _chart(app):
    return str(app.query_one("#weight-chart").content)


async def test_chart_renders_braille(make_app, db):
    _seed(db)
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        body = app.query_one("#body")
        body.viewing_date = "2026-07-28"
        body.horizon = "3m"
        body.reload()
        await pilot.pause()
        text = _chart(app)
    assert any(0x2800 <= ord(ch) <= 0x28FF for ch in text)


async def test_chart_is_multirow_not_a_sparkline(make_app, db):
    _seed(db)
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        body = app.query_one("#body")
        body.viewing_date = "2026-07-28"
        body.reload()
        await pilot.pause()
        lines = _chart(app).split("\n")
    assert len(lines) >= 8, f"only {len(lines)} rows — that is a sparkline"


async def test_chart_has_an_axis_and_date_labels(make_app, db):
    _seed(db)
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        body = app.query_one("#body")
        body.viewing_date = "2026-07-28"
        body.horizon = "3m"
        body.reload()
        await pilot.pause()
        text = _chart(app)
    assert "└" in text
    assert "Jul" in text


async def test_chart_labels_the_window_extent(make_app, db):
    """v1 plotted the last 30 entries while labelling as if it were the window."""
    add_weight(db, kg=84.8, date="2026-07-01", at=1)
    add_weight(db, kg=79.9, date="2026-07-20", at=2)
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        body = app.query_one("#body")
        body.viewing_date = "2026-07-28"
        body.horizon = "3m"
        body.reload()
        await pilot.pause()
        text = _chart(app)
    assert "84.8" in text and "79.9" in text


async def test_empty_chart_says_so(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "no data" in _chart(app).lower()


async def test_zoom_changes_the_horizon_and_the_header_shows_the_span(make_app, db):
    _seed(db)
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        body = app.query_one("#body")
        assert body.horizon == "1m"
        before = str(app.query_one("#weight-head").content)
        await pilot.press("plus")
        await pilot.pause()
        assert body.horizon == "MTD"
        assert str(app.query_one("#weight-head").content) != before


async def test_zoom_clamps_at_all(make_app, db):
    _seed(db)
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        for _ in range(10):
            await pilot.press("plus")
        assert app.query_one("#body").horizon == "all"


async def test_a_wider_window_shows_more_of_the_series(make_app, db):
    add_weight(db, kg=90.0, date="2026-01-05", at=1)
    add_weight(db, kg=80.0, date="2026-07-20", at=2)
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        body = app.query_one("#body")
        body.viewing_date = "2026-07-28"
        body.horizon = "1m"
        body.reload()
        await pilot.pause()
        narrow = _chart(app)
        body.horizon = "1y"
        body.reload()
        await pilot.pause()
        wide = _chart(app)
    assert "90" not in narrow
    assert "90" in wide


# ── consequence-bearing feedback ─────────────────────────────────────────
async def test_weigh_in_reports_its_trend_not_just_the_number(make_app, db, type_into):
    # Inside the 7-day window ending 2026-08-27; a reading on the 20th would be
    # outside it, and weight_delta would correctly report no trend.
    add_weight(db, kg=78.6, date="2026-08-22", at=1)
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await pilot.pause()
        seen = []
        app.notify = lambda msg, **kw: seen.append(str(msg))
        await pilot.press("w")
        await type_into(pilot, "78.2")
        await pilot.press("enter")
        await pilot.pause()
    assert any("78.2" in m for m in seen)
    assert any("7d" in m for m in seen), f"no trend in the feedback: {seen}"


async def test_first_ever_weigh_in_reports_without_a_trend(make_app, db, type_into):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await pilot.pause()
        seen = []
        app.notify = lambda msg, **kw: seen.append(str(msg))
        await pilot.press("w")
        await type_into(pilot, "78.2")
        await pilot.press("enter")
        await pilot.pause()
    assert any("78.2" in m for m in seen)


async def test_labelled_food_reports_the_day_total(make_app, db, type_into):
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await pilot.pause()
        seen = []
        app.notify = lambda msg, **kw: seen.append(str(msg))
        await pilot.press("f")
        await type_into(pilot, "salad =610")
        await pilot.press("enter")
        await pilot.pause()
    assert any("610" in m for m in seen)
    assert any("today" in m or "BMR" in m for m in seen), f"no day context: {seen}"


async def test_food_feedback_uses_bmr_when_a_profile_exists(
    make_app, make_cfg, db, type_into
):
    add_weight(db, kg=80.0, date="2026-08-27", at=1)
    cfg = make_cfg(height_cm=180, sex="male", birthday="1996-08-27")
    app = make_app(cfg=cfg, now=lambda: NOW)
    async with app.run_test() as pilot:
        await pilot.pause()
        seen = []
        app.notify = lambda msg, **kw: seen.append(str(msg))
        body = app.query_one("#body")
        body.viewing_date = "2026-08-27"
        await pilot.press("f")
        await type_into(pilot, "salad =610")
        await pilot.press("enter")
        await pilot.pause()
    assert any("BMR" in m for m in seen), f"expected a BMR comparison: {seen}"


async def test_delete_confirm_names_the_row(make_app, db):
    add_food(db, description="salad", kcal=610, source="labeled", date="2026-08-27", at=1)
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await pilot.pause()
        body = app.query_one("#body")
        body.viewing_date = "2026-08-27"
        body.reload()
        await pilot.pause()
        seen = []
        app.notify = lambda msg, **kw: seen.append(str(msg))
        await pilot.press("x")
        await pilot.pause()
    assert any("salad" in m for m in seen), f"confirm did not name the row: {seen}"
    assert any("610" in m for m in seen)


async def test_weight_delete_confirm_names_the_reading(make_app, db):
    add_weight(db, kg=78.2, date="2026-08-27", at=1)
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        seen = []
        app.notify = lambda msg, **kw: seen.append(str(msg))
        await pilot.press("x")
        await pilot.pause()
    assert any("78.2" in m for m in seen), f"confirm did not name the reading: {seen}"


async def test_delete_mentions_undo(make_app, db):
    add_food(db, description="salad", kcal=610, source="labeled", date="2026-08-27", at=1)
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await pilot.pause()
        body = app.query_one("#body")
        body.viewing_date = "2026-08-27"
        body.reload()
        await pilot.pause()
        seen = []
        app.notify = lambda msg, **kw: seen.append(str(msg))
        await pilot.press("x")
        await pilot.press("y")
        await pilot.pause()
    assert any("undo" in m for m in seen), f"no undo hint after deleting: {seen}"
