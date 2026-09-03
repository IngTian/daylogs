import pytest

from daylogs.horizon import HORIZONS
from daylogs.moneyview import SORT_FIELDS, MoneyView, ViewError


def V(**kw):
    return MoneyView(anchor=kw.pop("anchor", "2026-08-28"), **kw)


# ── span, via the shared horizon module ──────────────────────────────────
def test_default_horizon_is_month_to_date():
    v = V()
    assert v.horizon == "MTD"
    assert (v.span().start, v.span().end) == ("2026-08-01", "2026-08-28")


def test_one_week_really_means_seven_days_not_the_whole_month():
    """v2 filtered by month, so a short horizon silently pulled 31 days."""
    v = V(horizon="1w")
    assert (v.span().start, v.span().end) == ("2026-08-22", "2026-08-28")


def test_ytd_spans_the_year_so_far():
    v = V(horizon="YTD")
    assert v.span().start == "2026-01-01"
    assert len(v.months()) == 8


def test_all_is_unbounded():
    v = V(horizon="all")
    assert v.span().start is None
    assert v.months() == []


def test_months_touched_can_cross_a_boundary():
    assert V(anchor="2026-01-05", horizon="1m").months() == ["2025-12", "2026-01"]


def test_label_comes_from_the_span():
    assert "AUGUST 2026" in V().label()
    assert V(horizon="all").label() == "ALL TIME"
    assert "2026 YTD" in V(horizon="YTD").label()


# ── widen / narrow cycles the shared horizon list ────────────────────────
def test_widen_and_narrow_walk_the_horizon_list_and_clamp():
    v = V(horizon="1w")
    seen = []
    for _ in range(len(HORIZONS) + 1):
        v.widen()
        seen.append(v.horizon)
    assert seen[-1] == "all"
    for _ in range(len(HORIZONS) + 1):
        v.narrow()
    # `1d`, not the `1w` it started on: narrowing walks past the starting point and
    # clamps at the narrow end, which is now 1d — the list gained 1d and 3d for the
    # hour views.
    assert v.horizon == "1d"


# ── stepping ─────────────────────────────────────────────────────────────
def test_step_moves_by_the_active_horizon():
    week = V(horizon="1w")
    week.step(-1)
    assert week.anchor == "2026-08-21"
    mtd = V(horizon="MTD")
    mtd.step(-1)
    assert mtd.anchor == "2026-07-28"
    year = V(horizon="1y")
    year.step(1)
    assert year.anchor == "2027-08-28"


def test_step_is_a_no_op_for_all():
    v = V(horizon="all")
    v.step(-1)
    assert v.anchor == "2026-08-28"


def test_step_clamps_into_a_shorter_month():
    v = V(anchor="2026-03-31", horizon="MTD")
    v.step(-1)
    assert v.anchor == "2026-02-28"


# ── calendar marker ──────────────────────────────────────────────────────
def test_marker_only_for_month_to_date_on_the_running_month():
    assert V().is_single_current_month("2026-08-28") is True
    assert V(anchor="2026-07-28").is_single_current_month("2026-08-28") is False
    assert V(horizon="1w").is_single_current_month("2026-08-28") is False
    assert V(horizon="all").is_single_current_month("2026-08-28") is False


# ── sort ─────────────────────────────────────────────────────────────────
def test_same_field_twice_flips_direction():
    v = V(sort_field="date", sort_desc=True)
    v.set_sort("date")
    assert v.sort_desc is False
    v.set_sort("date")
    assert v.sort_desc is True


def test_different_field_switches_and_resets_to_descending():
    v = V(sort_field="date", sort_desc=False)
    v.set_sort("amount")
    assert (v.sort_field, v.sort_desc) == ("amount", True)


def test_unknown_sort_field_rejected():
    with pytest.raises(ViewError):
        V().set_sort("nonsense")


def test_sort_fields_are_the_declared_three():
    assert SORT_FIELDS == ("date", "amount", "category")


# ── jump / goto ──────────────────────────────────────────────────────────
def test_jump_to_resets_the_anchor_and_clears_narrowing():
    v = V(anchor="2026-03-02", filter_text="coffee", filter_category="grocery",
          pane="expenses")
    v.jump_to("2026-08-28")
    assert v.anchor == "2026-08-28"
    assert v.filter_text == "" and v.filter_category is None


def test_goto_a_full_date():
    v = V()
    v.goto("2026-04-15")
    assert v.anchor == "2026-04-15"


def test_goto_a_bare_month_lands_on_its_last_day():
    """So `g 2026-06` under MTD shows the whole of June, not just the 1st."""
    v = V()
    v.goto("2026-06")
    assert v.anchor == "2026-06-30"
    assert v.span().start == "2026-06-01"


def test_goto_a_february_month_knows_its_length():
    v = V()
    v.goto("2026-02")
    assert v.anchor == "2026-02-28"


def test_goto_tolerates_whitespace():
    v = V()
    v.goto("  2026-06 ")
    assert v.anchor == "2026-06-30"


@pytest.mark.parametrize("bad", ["", "june", "2026", "2026-13", "26-06", "2026-02-30"])
def test_goto_rejects_junk(bad):
    with pytest.raises(ViewError):
        V().goto(bad)


# ── the escape stack ─────────────────────────────────────────────────────
def test_back_clears_text_filter_first():
    v = V(pane="expenses", filter_text="coffee", filter_category="grocery")
    assert v.back() is True
    assert v.filter_text == ""
    assert v.filter_category == "grocery"


def test_back_then_clears_category_and_returns_to_categories():
    v = V(pane="expenses", filter_category="grocery")
    assert v.back() is True
    assert v.filter_category is None
    assert v.pane == "categories"


def test_back_returns_false_when_there_is_nothing_to_unwind():
    assert V().back() is False


def test_back_does_not_touch_grouped_mode():
    v = V(pane="expenses", grouped=True, filter_text="x", filter_category="grocery")
    v.back()
    v.back()
    v.back()
    assert v.grouped is True


# ── grouping ─────────────────────────────────────────────────────────────
def test_toggle_collapsed_round_trips():
    v = V()
    v.toggle_collapsed("grocery")
    assert "grocery" in v.collapsed
    v.toggle_collapsed("grocery")
    assert "grocery" not in v.collapsed


def test_collapsed_holds_several_groups():
    v = V()
    v.toggle_collapsed("grocery")
    v.toggle_collapsed("restaurant")
    assert v.collapsed == frozenset({"grocery", "restaurant"})
