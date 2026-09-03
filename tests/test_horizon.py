import datetime as dt

import pytest

from daylogs import horizon as hz
from daylogs.horizon import (
    DEFAULT,
    HORIZONS,
    HorizonError,
    next_horizon,
    resolve,
    shift,
)

A = "2026-08-28"


def _length(span):
    """Inclusive day count, computed here rather than read from `Span.days`.

    `Span.days` had been deleted as dead and came back with the `1d`/`3d` horizons,
    which need it to decide whether a span is short enough to plot by the hour. These
    tests keep computing it independently on purpose: asserting boundary arithmetic
    against the same accessor the code uses would only prove it agrees with itself.
    """
    if span.start is None:
        return None
    return (dt.date.fromisoformat(span.end) - dt.date.fromisoformat(span.start)).days + 1


# ── resolution ───────────────────────────────────────────────────────────
def test_one_week_is_seven_days_inclusive():
    s = resolve("1w", anchor=A)
    assert (s.start, s.end) == ("2026-08-22", "2026-08-28")
    assert _length(s) == 7


def test_one_month_is_thirty_days():
    assert _length(resolve("1m", anchor=A)) == 30


def test_three_months_is_ninety_days():
    assert _length(resolve("3m", anchor=A)) == 90


def test_one_year_is_365_days():
    assert _length(resolve("1y", anchor=A)) == 365


def test_mtd_starts_at_the_first_of_the_anchor_month():
    s = resolve("MTD", anchor=A)
    assert (s.start, s.end) == ("2026-08-01", "2026-08-28")


def test_ytd_starts_at_january_first():
    s = resolve("YTD", anchor=A)
    assert (s.start, s.end) == ("2026-01-01", "2026-08-28")


def test_all_is_unbounded():
    s = resolve("all", anchor=A)
    assert s.start is None
    assert _length(s) is None
    assert s.months() == []


def test_unknown_horizon_rejected():
    with pytest.raises(HorizonError):
        resolve("nonsense", anchor=A)


def test_rolling_window_crosses_a_year_boundary():
    s = resolve("1m", anchor="2026-01-05")
    assert s.start == "2025-12-07"


def test_ytd_on_january_first_is_a_single_day():
    s = resolve("YTD", anchor="2026-01-01")
    assert (s.start, s.end) == ("2026-01-01", "2026-01-01")
    assert _length(s) == 1


# ── months touched (budgets are per month) ───────────────────────────────
def test_months_for_a_within_month_span():
    assert resolve("1w", anchor=A).months() == ["2026-08"]


def test_months_for_a_span_crossing_a_boundary():
    assert resolve("1m", anchor="2026-01-05").months() == ["2025-12", "2026-01"]


def test_months_for_ytd():
    m = resolve("YTD", anchor=A).months()
    assert m[0] == "2026-01" and m[-1] == "2026-08" and len(m) == 8


def test_months_for_a_year_crosses_years():
    m = resolve("1y", anchor=A).months()
    assert m[0] == "2025-08" and m[-1] == "2026-08"


# ── contains ─────────────────────────────────────────────────────────────
def test_labels_describe_the_actual_range():
    assert "AUGUST 2026" in resolve("MTD", anchor=A).label
    assert "28th" in resolve("MTD", anchor=A).label
    assert "2026 YTD" in resolve("YTD", anchor=A).label
    assert resolve("all", anchor=A).label == "ALL TIME"


def test_within_year_label_names_the_year_once():
    label = resolve("1w", anchor=A).label
    assert label.count("2026") == 1


def test_cross_year_label_names_both_years():
    label = resolve("1y", anchor=A).label
    assert "2025" in label and "2026" in label


def test_ordinal_suffixes():
    for day, want in (("2026-08-01", "1st"), ("2026-08-02", "2nd"), ("2026-08-03", "3rd"),
                      ("2026-08-04", "4th"), ("2026-08-11", "11th"), ("2026-08-21", "21st"),
                      ("2026-08-22", "22nd"), ("2026-08-23", "23rd")):
        assert want in resolve("MTD", anchor=day).label


# ── cycling ──────────────────────────────────────────────────────────────
def test_cycle_order_and_clamping():
    assert list(HORIZONS) == ["1d", "3d", "1w", "1m", "MTD", "3m", "YTD", "1y", "all"]
    assert next_horizon("1w", 1) == "1m"
    assert next_horizon("1w", -1) == "3d", "3d sits between a day and a week"
    assert next_horizon("3d", -1) == "1d"
    assert next_horizon("1d", -1) == "1d"
    assert next_horizon("all", 1) == "all"
    assert next_horizon("MTD", -1) == "1m"
    assert next_horizon("nonsense", 1) == DEFAULT


# ── shifting the anchor ──────────────────────────────────────────────────
def test_week_shifts_seven_days():
    assert shift("1w", A, -1) == "2026-08-21"
    assert shift("1w", A, 1) == "2026-09-04"


def test_month_and_mtd_shift_a_calendar_month():
    assert shift("1m", A, -1) == "2026-07-28"
    assert shift("MTD", A, -1) == "2026-07-28"


def test_quarter_shifts_three_months():
    assert shift("3m", A, -1) == "2026-05-28"


def test_year_horizons_shift_twelve_months():
    assert shift("1y", A, -1) == "2025-08-28"
    assert shift("YTD", A, -1) == "2025-08-28"


def test_shift_clamps_to_a_shorter_month():
    assert shift("MTD", "2026-03-31", -1) == "2026-02-28"


def test_shift_crosses_a_year_boundary():
    assert shift("MTD", "2026-01-15", -1) == "2025-12-15"


def test_all_does_not_shift():
    assert shift("all", A, -1) == A


def test_shift_rejects_an_unknown_horizon():
    with pytest.raises(HorizonError):
        shift("nonsense", A, -1)


# ── Axis: plotting against real dates ───────────────────────────────────────


def test_axis_uses_the_span_not_the_data():
    span = hz.resolve("1m", anchor="2026-08-28")
    ax = hz.axis(span, ["2026-08-27", "2026-08-28"])
    assert (ax.left, ax.right) == ("2026-07-30", "2026-08-28")


def test_axis_places_late_points_at_the_right_edge():
    """The bug: two readings a day apart were spread across a month-wide panel as
    a smooth climb. At true positions they sit together at the right."""
    span = hz.resolve("1m", anchor="2026-08-28")
    ax = hz.axis(span, ["2026-08-27", "2026-08-28"])
    fracs = ax.fractions(["2026-08-27", "2026-08-28"])
    assert fracs[1] == 1.0
    assert fracs[0] > 0.95


def test_axis_start_of_span_is_zero():
    span = hz.resolve("1m", anchor="2026-08-28")
    assert hz.axis(span, []).fraction("2026-07-30") == 0.0


def test_axis_midpoint_is_a_half():
    ax = hz.Axis("2026-08-01", "2026-08-11")
    assert ax.fraction("2026-08-06") == 0.5


def test_axis_clamps_dates_outside_the_span():
    ax = hz.Axis("2026-08-01", "2026-08-31")
    assert ax.fraction("2026-07-01") == 0.0
    assert ax.fraction("2026-09-30") == 1.0


def test_axis_for_an_unbounded_span_borrows_the_earliest_date():
    span = hz.resolve("all", anchor="2026-08-28")
    ax = hz.axis(span, ["2026-03-02", "2026-08-28"])
    assert ax.left == "2026-03-02"
    assert ax.fraction("2026-03-02") == 0.0


def test_axis_for_an_unbounded_span_with_no_data_does_not_crash():
    span = hz.resolve("all", anchor="2026-08-28")
    ax = hz.axis(span, [])
    assert (ax.left, ax.right) == ("2026-08-28", "2026-08-28")
    assert ax.fraction("2026-08-28") == 0.0


def test_axis_single_day_span_is_safe():
    """The date-only position stays 0.0: a bare date means midnight, and midnight is
    the start of the axis.

    The labels moved to hours when the `1d` horizon arrived — a one-day axis is a
    day wide, so an hour scale says more than a date repeated three times, and the
    tab header already carries the date. See
    `test_a_single_day_axis_is_labelled_in_hours`.
    """
    ax = hz.Axis("2026-08-28", "2026-08-28")
    assert ax.fraction("2026-08-28") == 0.0


def test_axis_labels_describe_the_span_ends_and_middle():
    """These used to come from the plotted points, which printed
    "Aug 27 / Aug 28 / Aug 28" for a month-long window."""
    ax = hz.Axis("2026-07-30", "2026-08-28")
    labels = ax.labels()
    assert labels[0] == "Jul 30"
    assert labels[-1] == "Aug 28"
    assert len(set(labels)) == 3


# ── resolve_goto: one rule, three callers ───────────────────────────────────


def test_goto_a_full_date_lands_on_itself():
    assert hz.resolve_goto("2026-06-15") == "2026-06-15"


def test_goto_a_bare_month_lands_on_its_last_day():
    """So `g 2026-06` under a month-to-date horizon gives the whole of June."""
    assert hz.resolve_goto("2026-06") == "2026-06-30"
    assert hz.resolve_goto("2026-02") == "2026-02-28"
    assert hz.resolve_goto("2024-02") == "2024-02-29"
    assert hz.resolve_goto("2026-12") == "2026-12-31"


def test_goto_result_is_always_a_valid_iso_date():
    """The bug this function exists to kill: two cloned copies appended `-01` to a
    value that was already a full date, yielding "2026-06-30-01" — which poisoned
    the tab's date and crashed the app on the next keypress."""
    for text in ("2026-06", "2026-06-15", " 2026-01 ", "2026-12"):
        dt.date.fromisoformat(hz.resolve_goto(text))


def test_goto_strips_surrounding_whitespace():
    assert hz.resolve_goto("  2026-06-15  ") == "2026-06-15"


def test_goto_rejects_an_impossible_date():
    with pytest.raises(hz.HorizonError, match="not a real date"):
        hz.resolve_goto("2026-02-31")


def test_goto_rejects_an_impossible_month():
    with pytest.raises(hz.HorizonError, match="not a real date"):
        hz.resolve_goto("2026-13")


def test_goto_rejects_anything_else_with_guidance():
    for text in ("", "nope", "june", "2026", "15-06-2026"):
        with pytest.raises(hz.HorizonError, match="give a date like"):
            hz.resolve_goto(text)


# ── 1d: the single-day window, and sub-day positions ────────────────────────


def test_one_day_is_the_narrowest_horizon():
    """Zooming in used to stop at a week, so there was no way to look at one day."""
    assert hz.HORIZONS[0] == "1d"
    assert hz.next_horizon("3d", -1) == "1d"
    assert hz.next_horizon("1d", -1) == "1d", "zoom in must clamp, not wrap"


def test_one_day_resolves_to_a_single_date():
    span = hz.resolve("1d", anchor="2026-08-28")
    assert (span.start, span.end) == ("2026-08-28", "2026-08-28")


def test_brackets_step_one_day_on_the_one_day_horizon():
    assert hz.shift("1d", "2026-08-28", -1) == "2026-08-27"
    assert hz.shift("1d", "2026-08-28", 1) == "2026-08-29"


def test_a_single_day_span_reads_as_one_date():
    """"Aug 28 – Aug 28 2026" is what the range branch produces, and it reads as a
    formatting bug rather than as a day."""
    label = hz.resolve("1d", anchor="2026-08-28").label
    assert "–" not in label, f"a one-day span rendered as a range: {label!r}"
    assert "Aug 28" in label and "2026" in label


def test_sub_day_positions_separate_two_readings_on_one_day():
    """The point of item 3: on a one-day axis, morning sits left of evening."""
    ax = hz.Axis("2026-08-28", "2026-08-28")
    morning = ax.fraction_at(dt.datetime(2026, 8, 28, 7, 0))
    evening = ax.fraction_at(dt.datetime(2026, 8, 28, 19, 0))
    assert 0.0 <= morning < evening <= 1.0, f"{morning} !< {evening}"
    assert morning == pytest.approx(7 / 24, abs=0.01)


def test_sub_day_positions_add_to_the_day_offset_on_a_longer_axis():
    ax = hz.Axis("2026-08-01", "2026-08-11")   # 10 days wide
    noon_on_the_sixth = ax.fraction_at(dt.datetime(2026, 8, 6, 12, 0))
    assert noon_on_the_sixth == pytest.approx(0.55, abs=0.01), "half a day past 0.5"


def test_midnight_matches_the_date_only_position():
    """Backwards compatibility: everything that positioned by date still lands
    where it did, so a long horizon is unchanged."""
    ax = hz.Axis("2026-08-01", "2026-08-11")
    assert ax.fraction_at(dt.datetime(2026, 8, 6, 0, 0)) == ax.fraction("2026-08-06")


def test_sub_day_positions_clamp_inside_the_axis():
    ax = hz.Axis("2026-08-01", "2026-08-11")
    assert ax.fraction_at(dt.datetime(2026, 7, 1, 12, 0)) == 0.0
    assert ax.fraction_at(dt.datetime(2026, 8, 11, 23, 59)) == 1.0


def test_fractions_at_maps_a_list():
    ax = hz.Axis("2026-08-28", "2026-08-28")
    out = ax.fractions_at(
        [dt.datetime(2026, 8, 28, 6, 0), dt.datetime(2026, 8, 28, 18, 0)]
    )
    assert len(out) == 2 and out[0] < out[1]


def test_a_single_day_axis_is_labelled_in_hours():
    """A one-day axis is a day wide, so dates say nothing an hour scale doesn't say
    better — and the tab header already carries the date."""
    ax = hz.Axis("2026-08-28", "2026-08-28")
    labels = ax.labels()
    assert labels == ("00:00", "12:00", "24:00"), labels


# ── 3d: hours across a few days ─────────────────────────────────────────────


def test_three_days_sits_between_one_day_and_a_week():
    assert list(hz.HORIZONS[:3]) == ["1d", "3d", "1w"]
    assert hz.next_horizon("1w", -1) == "3d"
    assert hz.next_horizon("3d", -1) == "1d"


def test_three_days_resolves_to_three_inclusive_days():
    span = hz.resolve("3d", anchor="2026-08-28")
    assert (span.start, span.end) == ("2026-08-26", "2026-08-28")
    assert span.days == 3


def test_brackets_step_three_days():
    assert hz.shift("3d", "2026-08-28", -1) == "2026-08-25"


def test_spans_up_to_three_days_are_hourly_and_longer_ones_are_not():
    assert hz.resolve("1d", anchor="2026-08-28").hourly is True
    assert hz.resolve("3d", anchor="2026-08-28").hourly is True
    assert hz.resolve("1w", anchor="2026-08-28").hourly is False
    assert hz.resolve("all", anchor="2026-08-28").hourly is False, "unbounded is never hourly"


def test_a_three_day_axis_is_labelled_with_weekday_and_clock():
    ax = hz.Axis("2026-08-26", "2026-08-28")   # Wed - Fri
    labels = ax.labels()
    assert labels == ("Wed 00:00", "Thu 12:00", "Fri 24:00"), labels


def test_the_last_afternoon_of_a_three_day_span_is_not_pinned_to_the_edge():
    """With the exclusive divisor a long chart pins its newest point to the right,
    which is right for "now" and wrong for a clock view: everything after midday on
    the final day would collapse onto one column."""
    ax = hz.Axis("2026-08-26", "2026-08-28")
    noon = ax.fraction_at(dt.datetime(2026, 8, 28, 12, 0))
    end = ax.fraction_at(dt.datetime(2026, 8, 28, 23, 59))
    assert noon == pytest.approx(2.5 / 3, abs=0.01)
    assert noon < end < 1.0 or end == pytest.approx(1.0, abs=0.001)
    assert noon < 0.9, f"midday on the last day should not be at the edge: {noon}"


def test_a_long_axis_still_pins_its_newest_point_to_the_right_edge():
    """The behaviour the month-wide chart relies on, unchanged."""
    span = hz.resolve("1m", anchor="2026-08-28")
    ax = hz.axis(span, ["2026-08-28"])
    assert ax.fraction_at(dt.datetime(2026, 8, 28, 18, 0)) == 1.0
