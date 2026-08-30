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
    render_expense,
    render_weigh,
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
def test_weigh_reads_a_bare_number():
    assert W("78.2").kg == 78.2


def test_weigh_plain_text_is_the_note():
    r = W("78.2 post-run")
    assert (r.kg, r.note) == (78.2, "post-run")


def test_a_weigh_note_containing_a_time_survives():
    """This used to lose the 6:50 AND re-stamp the timestamp to 06:50 — two fields
    corrupted by one entry."""
    r = W("79.4 weighed at 6:50 before food")
    assert r.note == "weighed at 6:50 before food"
    assert datetime.fromtimestamp(r.at, TZ).strftime("%H:%M") == NOW.strftime("%H:%M")


def test_a_weigh_note_starting_with_a_number_survives():
    assert W("80 80 was the goal").note == "80 was the goal"


def test_weigh_takes_a_time():
    r = W("78.2 post-run @07:30")
    assert datetime.fromtimestamp(r.at, TZ).strftime("%H:%M") == "07:30"


def test_weigh_rejects_a_tilde_and_says_what_it_would_have_set():
    with pytest.raises(ParseError, match="note"):
        W("78.2 ~post-run")


def test_weigh_rejects_an_implausible_value():
    with pytest.raises(ParseError, match="plausible weight"):
        W("900")


def test_weigh_needs_a_leading_number():
    with pytest.raises(ParseError, match="78.2"):
        W("heavy")


@pytest.mark.parametrize("bad", ["", "   ", "0", "-5"])
def test_weigh_rejects_empty_and_nonpositive(bad):
    """The guard is `0 < kg <= MAX_KG`; testing only 900 leaves its lower bound and the
    empty line unasserted."""
    with pytest.raises(ParseError):
        W(bad)


WEIGH_ROWS = [
    dict(kg=78.2, note="post-run", date="2026-08-20"),
    dict(kg=79.4, note="weighed at 6:50 before food", date="2026-08-22"),
    dict(kg=80.0, note="80 was the goal", date="2026-08-22"),
    dict(kg=81.5, note=None, date="2026-08-27"),
    dict(kg=77.0, note="felt !light", date="2026-08-27"),
]


@pytest.mark.parametrize("row", WEIGH_ROWS, ids=[str(r["kg"]) for r in WEIGH_ROWS])
def test_weigh_round_trips(row):
    got = W(render_weigh(row))
    assert got.kg == row["kg"]
    assert (got.note or None) == row["note"]
    assert got.date == row["date"]


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
def test_expense_reads_amount_description_and_category():
    r = E("12.40 lunch !restaurant")
    assert (r.amount, r.description, r.category) == (12.40, "lunch", "restaurant")


def test_the_amount_is_strictly_the_first_token():
    """Not "the first number found anywhere" — strictly first. That is what makes a
    numeric word inside a description safe."""
    r = E("127 750 shelf !grocery")
    assert r.amount == 127.0
    assert r.description == "750 shelf"


def test_a_missing_amount_names_a_valid_line():
    with pytest.raises(ParseError, match="12.40"):
        E("lunch !restaurant")


def test_plain_tokens_join_in_order_wherever_the_sigil_sits():
    assert E("127 Grocery !grocery Item X").description == "Grocery Item X"
    assert E("127 Grocery Item X !grocery").description == "Grocery Item X"


def test_a_description_containing_a_category_word_survives():
    """The headline bug: this used to store category=grocery and description
    "lunch at store restaurant"."""
    r = E("84.10 lunch at grocery store !restaurant")
    assert r.category == "restaurant"
    assert r.description == "lunch at grocery store"


def test_a_description_containing_a_time_survives():
    """`19:30` used to be consumed as the time of day."""
    r = E("60 dinner 19:30 reservation !restaurant")
    assert r.description == "dinner 19:30 reservation"


def test_a_description_that_is_a_category_word_survives():
    r = E("40 Restaurant Depot supplies !grocery")
    assert r.category == "grocery"
    assert r.description == "Restaurant Depot supplies"


def test_no_category_falls_back_to_other():
    """The escape hatch: record now, classify later. money_tab re-opens the prompt
    labelled `fix category`."""
    assert E("12.40 lunch").category == "other"


def test_an_unknown_category_names_the_valid_ones():
    with pytest.raises(ParseError, match="grocery"):
        E("12.40 lunch !pizza")


def test_a_repeated_category_is_an_error():
    with pytest.raises(ParseError, match="twice"):
        E("12.40 lunch !grocery !restaurant")


def test_a_note_may_contain_spaces():
    r = E("127 shelf !grocery ~receipt in wallet")
    assert r.note == "receipt in wallet"
    assert r.description == "shelf"


def test_a_note_stops_at_the_next_sigil():
    r = E("127 shelf ~receipt in wallet !grocery")
    assert (r.note, r.category, r.description) == ("receipt in wallet", "grocery", "shelf")


def test_no_note_is_none():
    assert E("12.40 lunch !restaurant").note is None


def test_a_date_may_be_given():
    assert E("12.40 lunch !restaurant @2026-06-15").date == "2026-06-15"


def test_a_negative_amount_is_a_refund():
    assert E("-24.99 returned shoes !grocery").amount == -24.99


def test_a_zero_amount_is_rejected():
    with pytest.raises(ParseError, match="non-zero"):
        E("0 lunch !restaurant")


def test_a_missing_description_is_rejected():
    with pytest.raises(ParseError, match="say what it was"):
        E("12.40 !restaurant")


def test_a_formatted_amount_is_accepted():
    assert E("$1,240.50 rent !housing").amount == 1240.50


def test_a_decimal_comma_is_still_rejected():
    with pytest.raises(ParseError, match="use a dot for decimals"):
        E("12,40 lunch !restaurant")


def test_an_escaped_sigil_stays_in_the_description():
    assert E(r"12.40 \!important thing !grocery").description == "!important thing"


# ── expense round trip ───────────────────────────────────────────────────
EXPENSE_ROWS = [
    dict(amount=12.40, description="lunch", category="restaurant", date="2026-08-20", note=None),
    dict(amount=84.10, description="lunch at grocery store", category="restaurant",
         date="2026-08-20", note=None),
    dict(amount=40.0, description="Restaurant Depot supplies", category="grocery",
         date="2026-08-20", note=None),
    dict(amount=60.0, description="dinner 19:30 reservation", category="restaurant",
         date="2026-08-20", note=None),
    dict(amount=-24.99, description="returned shoes", category="grocery",
         date="2026-01-02", note=None),
    dict(amount=127.0, description="750", category="grocery", date="2026-08-20",
         note="receipt in wallet"),
    dict(amount=9.0, description="buy !milk", category="grocery", date="2026-08-20",
         note="on the !corner"),
    dict(amount=5.0, description="50% off bin", category="other", date="2026-08-20", note=None),
]


@pytest.mark.parametrize("row", EXPENSE_ROWS, ids=[r["description"][:18] for r in EXPENSE_ROWS])
def test_expense_round_trips(row):
    """parse(render(row)) == row. This is the property that lets one grammar serve
    both entry and editing."""
    got = E(render_expense(row))
    for field in ("amount", "description", "category", "date", "note"):
        assert getattr(got, field) == row[field], field


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
    assert datetime.fromtimestamp(w.at, TZ).strftime("%H:%M") == "07:30"


def test_when_accepts_a_combined_date_and_time():
    w = resolve_when(["06-15/07:30"], now=NOW)
    assert w.date == "2026-06-15"
    assert datetime.fromtimestamp(w.at, TZ).strftime("%H:%M") == "07:30"


def test_a_date_and_a_time_may_arrive_as_two_tokens():
    w = resolve_when(["06-15", "07:30"], now=NOW)
    assert w.date == "2026-06-15"
    assert datetime.fromtimestamp(w.at, TZ).strftime("%H:%M") == "07:30"


def test_back_dating_without_a_time_keeps_the_wall_clock():
    """Collapsing to midnight would misreport a weigh-in."""
    w = resolve_when(["06-15"], now=NOW)
    assert datetime.fromtimestamp(w.at, TZ).strftime("%H:%M") == NOW.strftime("%H:%M")


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
