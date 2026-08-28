import datetime as dt

import pytest

from daybook import horizon as hz
from daybook.horizon import (
    DEFAULT,
    HORIZONS,
    HorizonError,
    next_horizon,
    resolve,
    shift,
)

A = "2026-08-28"


def _length(span):
    """Inclusive day count.

    `Span.days()` was deleted as dead — nothing in the app ever read it — but the
    boundary arithmetic it asserted is still worth guarding, so the tests compute
    it themselves rather than keeping an accessor alive for their own benefit.
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
    assert list(HORIZONS) == ["1w", "1m", "MTD", "3m", "YTD", "1y", "all"]
    assert next_horizon("1w", 1) == "1m"
    assert next_horizon("1w", -1) == "1w"
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
    ax = hz.Axis("2026-08-28", "2026-08-28")
    assert ax.fraction("2026-08-28") == 0.0
    assert ax.labels() == ("Aug 28",)


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
