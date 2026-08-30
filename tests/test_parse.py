from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from daybook.categories import slugs
from daybook.parse import (
    ParseError,
    parse_budget,
    parse_expense,
    parse_food,
    parse_profile,
    parse_recurring,
    parse_weigh,
    resolve_when,
)

TZ = ZoneInfo("America/Toronto")
NOW = datetime(2026, 8, 27, 19, 40, tzinfo=TZ)
SLUGS = slugs()


def W(raw):
    return parse_weigh(raw, now=NOW)


def F(raw):
    return parse_food(raw, now=NOW)


def E(raw):
    return parse_expense(raw, now=NOW, known_slugs=SLUGS)


def B(raw):
    return parse_budget(raw, now=NOW, known_slugs=SLUGS)


def R(raw):
    return parse_recurring(raw, now=NOW, known_slugs=SLUGS)


# ── weigh ────────────────────────────────────────────────────────────────
def test_weigh_bare_number():
    r = W("78.2")
    assert r.kg == 78.2
    assert r.note is None
    assert r.date == "2026-08-27"
    assert r.at == int(NOW.timestamp())


def test_weigh_with_note():
    assert W("78.2 post-run, dehydrated").note == "post-run, dehydrated"


def test_weigh_backdated_full_and_short():
    assert W("78.2 @2026-08-25").date == "2026-08-25"
    assert W("78.2 @08-25").date == "2026-08-25"


def test_weigh_explicit_time_sets_at_not_note():
    r = W("78.2 07:15")
    assert r.note is None
    assert datetime.fromtimestamp(r.at, TZ).hour == 7


def test_weigh_backdated_without_time_keeps_wall_clock():
    r = W("78.2 @08-25")
    got = datetime.fromtimestamp(r.at, TZ)
    assert (got.month, got.day, got.hour, got.minute) == (8, 25, 19, 40)


def test_weigh_backdated_time_uses_that_date():
    r = W("78.2 @08-25 07:15")
    got = datetime.fromtimestamp(r.at, TZ)
    assert (got.year, got.month, got.day, got.hour, got.minute) == (2026, 8, 25, 7, 15)


@pytest.mark.parametrize("bad", ["", "   ", "heavy", "0", "-5", "700"])
def test_weigh_rejects_missing_nonnumeric_and_absurd(bad):
    with pytest.raises(ParseError):
        W(bad)


def test_weigh_rejects_impossible_date():
    with pytest.raises(ParseError):
        W("78.2 @02-30")


def test_weigh_rejects_impossible_time():
    with pytest.raises(ParseError):
        W("78.2 25:00")


# ── food ─────────────────────────────────────────────────────────────────
def test_food_trailing_integer_is_calories():
    r = F("chicken caesar salad 610")
    assert r.description == "chicken caesar salad"
    assert r.kcal == 610


def test_food_without_calories_returns_none_for_estimation():
    r = F("chicken caesar salad")
    assert r.description == "chicken caesar salad"
    assert r.kcal is None


def test_food_leading_number_stays_in_description():
    r = F("2 eggs")
    assert r.description == "2 eggs"
    assert r.kcal is None


def test_food_preserves_decimal_formatting_in_a_description():
    assert F("12.40 oz steak").description == "12.40 oz steak"


def test_food_description_ending_in_number_needs_explicit_calories():
    r = F("2 eggs 2 slices toast 420")
    assert r.description == "2 eggs 2 slices toast"
    assert r.kcal == 420


def test_food_backdated_and_timed():
    r = F("ribeye 910 @08-25 13:05")
    assert r.description == "ribeye"
    assert r.kcal == 910
    assert r.date == "2026-08-25"
    assert datetime.fromtimestamp(r.at, TZ).hour == 13


def test_food_rejects_numeric_only_description():
    with pytest.raises(ParseError):
        F("610")


def test_food_rejects_empty():
    with pytest.raises(ParseError):
        F("   ")


def test_food_rejects_absurd_calories():
    with pytest.raises(ParseError):
        F("salad 99999")


def test_food_zero_calories_is_allowed():
    assert F("black coffee 0").kcal == 0


# ── expense ──────────────────────────────────────────────────────────────
def test_expense_amount_description_default_category():
    r = E("12.40 lunch")
    assert (r.amount, r.description, r.category, r.date) == (
        12.40,
        "lunch",
        "other",
        "2026-08-27",
    )


def test_expense_trailing_slug_becomes_category():
    r = E("12.40 lunch restaurant")
    assert (r.amount, r.description, r.category) == (12.40, "lunch", "restaurant")


def test_expense_slug_anywhere_is_consumed():
    r = E("84.10 grocery weekly shop")
    assert (r.amount, r.description, r.category) == (84.10, "weekly shop", "grocery")


def test_expense_only_the_first_slug_is_consumed():
    r = E("12.40 grocery restaurant run")
    assert r.category == "grocery"
    assert "restaurant" in r.description


def test_expense_backdated():
    assert E("84.10 weekly shop grocery @08-25").date == "2026-08-25"


def test_expense_negative_is_a_refund():
    r = E("-24.99 returned shoes entertainment")
    assert r.amount == -24.99
    assert r.description == "returned shoes"


def test_expense_currency_symbol_and_commas_tolerated():
    assert E("$1,240.50 rent housing").amount == 1240.50


@pytest.mark.parametrize("bad", ["", "lunch", "0 lunch", "12.40", "12.40 grocery"])
def test_expense_rejects_bad_input(bad):
    with pytest.raises(ParseError):
        E(bad)


def test_expense_rejects_more_than_two_decimal_places():
    with pytest.raises(ParseError):
        E("12.4056 lunch")


# ── budget ───────────────────────────────────────────────────────────────
def test_budget_amount_and_category_name_defaults_to_display():
    r = B("500 grocery")
    assert (r.amount, r.category, r.name) == (500.0, "grocery", "Grocery")


def test_budget_explicit_name():
    r = B("500 household staples grocery")
    assert (r.amount, r.category, r.name) == (500.0, "grocery", "household staples")


def test_budget_requires_known_category():
    with pytest.raises(ParseError):
        B("500 nonsense")


@pytest.mark.parametrize("bad", ["-500 grocery", "0 grocery", "grocery"])
def test_budget_rejects_bad_amount(bad):
    with pytest.raises(ParseError):
        B(bad)


# ── recurring ────────────────────────────────────────────────────────────
def test_recurring_defaults_to_monthly():
    r = R("20.99 streaming subscriptions")
    assert (r.cost, r.name, r.category, r.cycle) == (
        20.99,
        "streaming",
        "subscriptions",
        "monthly",
    )


def test_recurring_annual_keyword_consumed_not_in_name():
    r = R("99 cloud storage subscriptions annually")
    assert (r.cost, r.name, r.cycle) == (99.0, "cloud storage", "annually")


def test_recurring_explicit_monthly_keyword_consumed():
    r = R("20.99 streaming subscriptions monthly")
    assert (r.name, r.cycle) == ("streaming", "monthly")


def test_recurring_without_category_falls_back_to_other():
    assert R("20.99 mystery thing").category == "other"


def test_recurring_requires_name():
    with pytest.raises(ParseError):
        R("20.99 subscriptions")


def test_recurring_requires_positive_cost():
    with pytest.raises(ParseError):
        R("-5 streaming subscriptions")


# ── profile ──────────────────────────────────────────────────────────────


def test_profile_reads_all_three_in_one_go():
    p = parse_profile("180 male 1990-01-01")
    assert (p.height_cm, p.sex, p.birthday) == (180.0, "male", "1990-01-01")


def test_profile_is_order_free():
    """Recognised by shape, so there is no argument order to remember."""
    a = parse_profile("1990-01-01 female 165")
    b = parse_profile("165 1990-01-01 female")
    assert a == b


def test_profile_accepts_a_partial_update():
    p = parse_profile("181")
    assert p.height_cm == 181.0
    assert p.sex is None and p.birthday is None
    assert p.fields() == {"height_cm": 181.0}


def test_profile_accepts_a_cm_suffix():
    assert parse_profile("175cm").height_cm == 175.0


def test_profile_accepts_short_sex_forms():
    assert parse_profile("m").sex == "male"
    assert parse_profile("f").sex == "female"


def test_profile_accepts_a_fractional_height():
    assert parse_profile("180.5").height_cm == 180.5


def test_profile_rejects_an_empty_line():
    with pytest.raises(ParseError):
        parse_profile("   ")


def test_profile_rejects_an_implausible_height():
    with pytest.raises(ParseError, match="plausible height"):
        parse_profile("12")
    with pytest.raises(ParseError, match="plausible height"):
        parse_profile("400")


def test_profile_rejects_an_impossible_date():
    with pytest.raises(ParseError, match="not a real date"):
        parse_profile("1990-13-01")


def test_profile_names_the_token_it_could_not_place():
    with pytest.raises(ParseError, match="purple"):
        parse_profile("purple")


def test_profile_fields_omits_what_was_not_given():
    assert parse_profile("female").fields() == {"sex": "female"}


def test_profile_is_pure_and_needs_no_clock():
    """Every other grammar takes `now`; this one has nothing time-relative in it,
    so it must not acquire a hidden dependency on the clock."""
    import inspect

    assert "now" not in inspect.signature(parse_profile).parameters


# ── amounts: a comma is a thousands separator, never a decimal point ──────


def test_a_decimal_comma_is_rejected_rather_than_silently_multiplied():
    """`12,40` used to parse as 1240 — a $12.40 lunch recorded as $1,240.00 with no
    complaint. Weights escaped the consequence only because 782 kg fails a
    plausibility check that expenses have no equivalent of."""
    with pytest.raises(ParseError, match="use a dot for decimals"):
        E("12,40 lunch restaurant")


def test_the_decimal_comma_error_suggests_the_right_line():
    with pytest.raises(ParseError, match=r"12\.40"):
        E("12,40 lunch restaurant")


def test_thousands_separators_still_work():
    assert E("$1,240.50 rent housing").amount == 1240.5
    assert E("1,240 rent housing").amount == 1240.0


def test_a_grouped_thousands_amount_with_several_groups_works():
    assert E("1,234,567.89 house housing").amount == 1234567.89


def test_a_decimal_comma_in_a_weight_is_rejected_too():
    with pytest.raises(ParseError, match="use a dot for decimals"):
        W("78,2")


# ── @ shape resolution ──────────────────────────────────────────────────────
def test_when_defaults_to_now():
    w = resolve_when([], now=NOW)
    assert w.date == NOW.date().isoformat()


def test_when_accepts_a_full_date():
    assert resolve_when(["2026-06-15"], now=NOW).date == "2026-06-15"


def test_when_accepts_a_month_day_in_the_current_year():
    assert resolve_when(["06-15"], now=NOW).date == "2026-06-15"


def test_when_accepts_a_time_and_keeps_todays_date():
    w = resolve_when(["07:30"], now=NOW)
    assert w.date == NOW.date().isoformat()
    assert datetime.fromtimestamp(w.at).strftime("%H:%M") == "07:30"


def test_when_accepts_a_combined_date_and_time():
    w = resolve_when(["06-15/07:30"], now=NOW)
    assert w.date == "2026-06-15"
    assert datetime.fromtimestamp(w.at).strftime("%H:%M") == "07:30"


def test_a_date_and_a_time_may_arrive_as_two_tokens():
    w = resolve_when(["06-15", "07:30"], now=NOW)
    assert w.date == "2026-06-15"
    assert datetime.fromtimestamp(w.at).strftime("%H:%M") == "07:30"


def test_back_dating_without_a_time_keeps_the_wall_clock():
    """Collapsing to midnight would misreport a weigh-in."""
    w = resolve_when(["06-15"], now=NOW)
    assert datetime.fromtimestamp(w.at).strftime("%H:%M") == NOW.strftime("%H:%M")


def test_two_dates_is_an_error():
    with pytest.raises(ParseError, match="date twice"):
        resolve_when(["06-15", "07-20"], now=NOW)


def test_two_times_is_an_error():
    with pytest.raises(ParseError, match="time twice"):
        resolve_when(["07:30", "08:30"], now=NOW)


def test_an_unparseable_when_names_the_shapes():
    with pytest.raises(ParseError, match="@2026-08-24"):
        resolve_when(["june"], now=NOW)


def test_an_impossible_date_is_rejected():
    with pytest.raises(ParseError, match="not a real date"):
        resolve_when(["02-31"], now=NOW)


def test_an_impossible_time_is_rejected():
    with pytest.raises(ParseError, match="not a valid time"):
        resolve_when(["25:00"], now=NOW)
