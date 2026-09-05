import datetime as dt
from zoneinfo import ZoneInfo

from helpers import go_body

from daylogs.body import add_food, add_weight

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
        await go_body(pilot, app)
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
        await go_body(pilot, app)
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
        await go_body(pilot, app)
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
        await go_body(pilot, app)
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
        await go_body(pilot, app)
        await pilot.pause()
        assert "no data" in _chart(app).lower()


async def test_zoom_changes_the_horizon_and_the_header_shows_the_span(make_app, db):
    _seed(db)
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        body = app.query_one("#body")
        assert body.horizon == "1m"
        before = str(app.query_one("#weight-head").content)
        await pilot.press("plus")
        await pilot.pause()
        assert body.horizon == "1w"
        assert str(app.query_one("#weight-head").content) != before


async def test_zoom_clamps_at_both_ends(make_app, db):
    """Wrapping from `all` back to `1d` on a keypress reads as a glitch.

    Both ends, in one test: the old version only pressed one key and so only ever
    covered one clamp, which meant the other end was never exercised at all.
    """
    _seed(db)
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        body = app.query_one("#body")
        for _ in range(10):
            await pilot.press("minus")
        assert body.horizon == "all", "zooming out must stop at the widest horizon"
        for _ in range(20):
            await pilot.press("plus")
        assert body.horizon == "1d", "zooming in must stop at the narrowest horizon"


async def test_a_wider_window_shows_more_of_the_series(make_app, db):
    add_weight(db, kg=90.0, date="2026-01-05", at=1)
    add_weight(db, kg=80.0, date="2026-07-20", at=2)
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
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
        await go_body(pilot, app)
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
        await go_body(pilot, app)
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
        await go_body(pilot, app)
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
        await go_body(pilot, app)
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
        await go_body(pilot, app)
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
        await go_body(pilot, app)
        await pilot.pause()
        # shift+tab: weight is one step back along weight / food / activity.
        await pilot.press("shift+tab")
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
        await go_body(pilot, app)
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


# ── hours: 1d and 3d plot every reading at its real time ─────────────────


async def test_a_three_day_window_plots_both_of_a_days_weigh_ins(make_app, db):
    """The point of items 1d/3d. On a month-wide window the per-day collapse keeps
    one reading; zoomed in, both appear, at their own hours.
    """
    import datetime as dt
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Toronto")
    morning = int(dt.datetime(2026, 8, 28, 7, 0, tzinfo=tz).timestamp())
    evening = int(dt.datetime(2026, 8, 28, 21, 0, tzinfo=tz).timestamp())
    add_weight(db, kg=80.4, date="2026-08-28", at=morning)
    add_weight(db, kg=79.8, date="2026-08-28", at=evening)

    app = make_app(now=lambda: dt.datetime(2026, 8, 28, 22, 0, tzinfo=tz))
    async with app.run_test(size=(140, 34)) as pilot:
        body = await go_body(pilot, app)
        body.horizon = "1m"
        body.reload()
        await pilot.pause()
        monthly = _chart(app)

        body.horizon = "3d"
        body.reload()
        await pilot.pause()
        three_day = _chart(app)

    # Asserted against what is *plotted*, not against the axis labels. The labels used
    # to be the evidence here, and they no longer can be: the extent now describes every
    # reading in the window rather than only the drawn points, precisely so a week does
    # not claim a top of 81.85 while an 82.65 sits inside it. Both labels are therefore
    # present in both views, and the difference to assert is the number of points.
    from daylogs.body import weight_points_between, weight_series_between

    collapsed = weight_series_between(db, start="2026-08-28", end="2026-08-28")
    every = weight_points_between(db, start="2026-08-28", end="2026-08-28")
    assert [kg for _, kg, _ in collapsed] == [80.4], "the collapse keeps the morning one"
    assert [kg for _, kg in every] == [80.4, 79.8], "the zoomed view has both"
    assert monthly != three_day, "the two windows drew the same picture"
    # And the labels describe the window in both, which is the point of the extent change.
    for text in (monthly, three_day):
        assert "80.4" in text and "79.8" in text


async def test_a_three_day_axis_is_labelled_by_the_clock(make_app, db):
    import datetime as dt
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Toronto")
    add_weight(db, kg=80.0, date="2026-08-28",
               at=int(dt.datetime(2026, 8, 28, 7, 0, tzinfo=tz).timestamp()))
    app = make_app(now=lambda: dt.datetime(2026, 8, 28, 22, 0, tzinfo=tz))
    async with app.run_test(size=(140, 34)) as pilot:
        body = await go_body(pilot, app)
        body.horizon = "3d"
        body.reload()
        await pilot.pause()
        chart_text = _chart(app)
    assert "00:00" in chart_text, f"no clock on the axis:\n{chart_text}"
    assert "24:00" in chart_text


# ── the calories chart ───────────────────────────────────────────────────
# One panel, three series, cycled by `c`. A fourth panel does not fit a 110-column
# screen, and the axis, the horizon and the width arithmetic are already here.

DAY = "2026-09-03"
_PROFILE = dict(height_cm=180, sex="male", birthday="1996-01-01", activity="desk")
# 80 kg at 180 cm, male, 30: Mifflin-St Jeor gives 1,780, and a desk day 2,136.
_DESK_BURN = 2136


def _strip(app):
    return str(app.query_one("#trend-title").content)


BLANK = "⠀"


def _plot_rows(text: str) -> list[str]:
    """Just the plotted rows — not the `└───` rule or the x-label row beneath it."""
    return [r for r in text.splitlines() if "│" in r or "┼" in r]


def _floor_label(text: str) -> str:
    return _plot_rows(text)[-1].replace("┼", "│").split("│")[0].strip()


async def _at(app, date=DAY):
    body = app.query_one("#body")
    body.viewing_date = date
    body.reload()
    return body


async def test_c_cycles_the_chart_through_weight_intake_and_net(make_app, db):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        body = app.query_one("#body")
        assert body.chart_mode == "weight"
        for expected in ("intake", "net", "weight"):
            await pilot.press("c")
            await pilot.pause()
            assert body.chart_mode == expected, f"c did not reach {expected}"


async def test_the_panel_names_every_series_and_marks_the_active_one(make_app, db):
    """The same strip Body's sub-views and Money's panes use, so the key is
    discoverable rather than something you have to be told about."""
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        strip = _strip(app)
        for name in ("weight", "intake", "net"):
            assert name in strip, f"{name} is missing from the strip: {strip!r}"
        assert "[b]weight[/b]" in strip
        await pilot.press("c")
        await pilot.pause()
        assert "[b]intake[/b]" in _strip(app)


async def test_the_intake_chart_plots_the_daily_totals(make_app, db, make_cfg):
    add_food(db, description="a", kcal=1500, source="labeled", date="2026-09-01", at=1)
    add_food(db, description="b", kcal=2500, source="labeled", date="2026-09-02", at=2)
    app = make_app(cfg=make_cfg(**_PROFILE))
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        body = await _at(app)
        body.chart_mode = "intake"
        body.reload()
        await pilot.pause()
        text = _chart(app)
    assert any(0x2800 <= ord(ch) <= 0x28FF for ch in text), f"no braille: {text!r}"
    assert "2500" in text, f"the window's peak is not labelled: {text!r}"
    # Calories are a magnitude, so the floor is zero rather than the series minimum —
    # otherwise a run of similar days reads as a climb from nothing.
    assert _floor_label(text) == "0", f"floor is not 0: {text!r}"


async def test_the_net_chart_plots_intake_against_each_days_own_burn(make_app, db, make_cfg):
    """The whole point of the series: a gym day must move only its own point. Against
    a single day's burn every point would shift together."""
    from daylogs.body import add_activity

    add_weight(db, kg=80.0, date="2026-09-01", at=1)
    add_food(db, description="a", kcal=2000, source="labeled", date="2026-09-01", at=2)
    add_food(db, description="b", kcal=2000, source="labeled", date="2026-09-02", at=3)
    add_activity(db, description="gym", date="2026-09-02", at=4, factor=1.6,
                 source="estimated")
    app = make_app(cfg=make_cfg(**_PROFILE))
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        body = await _at(app)
        body.chart_mode = "net"
        body.reload()
        await pilot.pause()
        text = _chart(app)
    # 2,000 − 2,136 = −136 on the desk day; 2,000 − 2,848 = −848 on the gym day.
    assert "-848" in text, f"the deepest deficit is not labelled: {text!r}"
    assert "-136" not in text or "-848" in text


async def test_the_net_chart_shows_where_zero_falls(make_app, db, make_cfg):
    """A deficit and a surplus draw the identical line without it."""
    add_weight(db, kg=80.0, date="2026-09-01", at=1)
    add_food(db, description="a", kcal=1000, source="labeled", date="2026-09-01", at=2)
    add_food(db, description="b", kcal=3500, source="labeled", date="2026-09-02", at=3)
    app = make_app(cfg=make_cfg(**_PROFILE))
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        body = await _at(app)
        body.chart_mode = "net"
        body.reload()
        await pilot.pause()
        text = _chart(app)
    assert "┼" in text, f"a signed chart with no zero reference: {text!r}"


async def test_an_all_deficit_net_chart_puts_zero_at_the_ceiling(make_app, db, make_cfg):
    add_weight(db, kg=80.0, date="2026-09-01", at=1)
    add_food(db, description="a", kcal=1000, source="labeled", date="2026-09-01", at=2)
    app = make_app(cfg=make_cfg(**_PROFILE))
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        body = await _at(app)
        body.chart_mode = "net"
        body.reload()
        await pilot.pause()
        text = _chart(app)
    assert text.splitlines()[0].split("│")[0].strip() == "0", f"no ceiling: {text!r}"
    assert "┼" not in text, "a rule that repeats the extent label"


async def test_the_weight_chart_keeps_fitting_itself(make_app, db):
    """Anchored at zero a 70-75 kg series is a flat line at the top of the panel, so
    weight must not inherit the calorie series' floor."""
    for day, kg in (("2026-09-01", 80.0), ("2026-09-02", 79.5)):
        add_weight(db, kg=kg, date=day, at=int(day[-2:]))
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        body = await _at(app)
        body.reload()
        await pilot.pause()
        text = _chart(app)
    assert "79.5" in text, f"the series floor is not its own minimum: {text!r}"
    assert "┼" not in text


async def test_a_calorie_chart_with_nothing_logged_says_so(make_app, db, make_cfg):
    app = make_app(cfg=make_cfg(**_PROFILE))
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        body = await _at(app)
        body.chart_mode = "net"
        body.reload()
        await pilot.pause()
        assert "no data" in _chart(app).lower()


async def test_the_chart_series_survives_a_horizon_change(make_app, db, make_cfg):
    """`+`/`-` and `c` are independent axes of the same panel; zooming must not reset
    which series you were reading."""
    add_food(db, description="a", kcal=1500, source="labeled", date="2026-09-01", at=1)
    app = make_app(cfg=make_cfg(**_PROFILE))
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        body = app.query_one("#body")
        await pilot.press("c")
        await pilot.pause()
        assert body.chart_mode == "intake"
        await pilot.press("minus")
        await pilot.pause()
        assert body.chart_mode == "intake", "zooming reset the series"


async def test_the_calorie_series_is_plotted_against_its_dates(make_app, db, make_cfg):
    """The invariant the weight chart already follows. Two days inside a three-month
    window belong at the right edge, not spread across it — index spacing rescales the
    x-axis to the sample count and turns two days into a quarter-long trend."""
    add_food(db, description="a", kcal=1500, source="labeled", date="2026-09-01", at=1)
    add_food(db, description="b", kcal=2500, source="labeled", date="2026-09-02", at=2)
    app = make_app(cfg=make_cfg(**_PROFILE))
    async with app.run_test(size=(120, 34)) as pilot:
        await go_body(pilot, app)
        body = await _at(app)
        body.chart_mode = "intake"
        body.horizon = "3m"
        body.reload()
        await pilot.pause()
        rows = _plot_rows(_chart(app))
    plot = [r.replace("┼", "│").split("│", 1)[1] for r in rows]
    width = len(plot[0])
    left = {ch for r in plot for ch in r[: int(width * 0.75)]}
    assert left <= {BLANK}, "two days were spread across a three-month window"
    assert any(ch != BLANK for r in plot for ch in r[int(width * 0.75) :])


async def test_food_feedback_names_burn_when_a_level_is_set(make_app, make_cfg, db):
    """The toast and the FOOD header describe the same day, so they must name the same
    baseline. The toast asked `compute_bmr` directly, so with a level set the header said
    net against `burn` while the toast said "vs BMR" in the same instant."""
    from daylogs.body import add_weight as _aw

    _aw(db, kg=80.0, date="2026-08-27", at=1)
    cfg = make_cfg(height_cm=180, sex="male", birthday="1996-01-01", activity="desk")
    app = make_app(cfg=cfg, now=lambda: NOW)
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        seen = []
        app.notify = lambda msg, **kw: seen.append(str(msg))
        body = app.query_one("#body")
        body.viewing_date = "2026-08-27"
        await pilot.press("f")
        for ch in "salad =610":
            await pilot.press("space" if ch == " " else ch)
        await pilot.press("enter")
        await pilot.pause()
        panel = str(app.query_one("#energy-body").content)
    assert any("burn" in m for m in seen), f"the toast does not name burn: {seen}"
    assert not any("BMR" in m for m in seen), f"the toast still says BMR: {seen}"
    # The panel, not the FOOD header: that header describes the window of rows beneath it
    # now, and the day's baseline is stated once, where the arithmetic that uses it lives.
    assert "burn" in panel, f"the panel should be naming burn too: {panel!r}"


async def test_an_unchanged_weigh_in_reports_a_neutral_arrow(make_app, db, type_into):
    """The third site drawing this arrow: the weigh-in toast. Re-logging the same number
    is a real thing to do, and it used to answer `▲0`."""
    add_weight(db, kg=78.2, date="2026-08-22", at=1)
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        seen = []
        app.notify = lambda msg, **kw: seen.append(str(msg))
        await pilot.press("w")
        await type_into(pilot, "78.2")
        await pilot.press("enter")
        await pilot.pause()
    trend = [m for m in seen if "7d" in m]
    assert trend, f"no trend in the feedback: {seen}"
    assert "→" in trend[0], f"an unchanged weigh-in is not flagged as unchanged: {trend}"
