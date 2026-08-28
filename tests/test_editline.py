"""The edit grammar, and the round trip the entry grammar could not do.

Every "trap" case below was verified to corrupt two fields at once when a stored
row was rendered into the *entry* grammar and re-parsed. They are the reason
editline.py exists, so they are the core of its test suite rather than an
afterthought.
"""

import pytest

from daybook import editline as el
from daybook.parse import ParseError


def row(**kw):
    """A stand-in for a sqlite3.Row — indexable by column name."""
    return kw


# ── splitting ────────────────────────────────────────────────────────────
def test_fields_are_split_and_stripped():
    assert el.split_fields("78.2 | post-run | 2026-08-27") == [
        "78.2",
        "post-run",
        "2026-08-27",
    ]


def test_an_empty_segment_survives_as_empty():
    assert el.split_fields("78.2 |  | 2026-08-27") == ["78.2", "", "2026-08-27"]


def test_an_escaped_pipe_is_content_not_a_separator():
    """A row whose text contains a pipe must stay editable — an uneditable row is a
    dead end with no way out from inside the app."""
    assert el.split_fields(r"12.40 | soup \| salad | restaurant") == [
        "12.40",
        "soup | salad",
        "restaurant",
    ]


def test_rendering_escapes_a_pipe_so_it_round_trips():
    line = el.render_expense(
        row(amount=12.4, description="soup | salad", category="restaurant", date="2026-08-27")
    )
    assert el.parse_expense(line)["description"] == "soup | salad"


def test_too_many_fields_is_an_error_not_a_silent_drop():
    with pytest.raises(ParseError, match="too many fields"):
        el.parse_weight("81 | note | 2026-08-27 | extra")


# ── omitted vs emptied ───────────────────────────────────────────────────
def test_an_omitted_trailing_field_is_left_alone():
    """`81.5` alone is a quick correction that keeps the note and the date."""
    assert el.parse_weight("81.5") == {"kg": 81.5}


def test_a_provided_empty_field_clears_it():
    got = el.parse_weight("81.5 |  | 2026-08-27")
    assert got["note"] == ""
    assert "note" in got


def test_clearing_uses_empty_string_not_none():
    """`_update` drops None values, so None would read as "leave it alone" and an
    emptied note would silently survive the edit."""
    assert el.parse_weight("81.5 | ")["note"] == ""


def test_a_required_field_cannot_be_emptied():
    with pytest.raises(ParseError, match="cannot be empty"):
        el.parse_expense(" | lunch | restaurant")


def test_a_line_that_changes_nothing_is_rejected():
    with pytest.raises(ParseError, match="nothing to change"):
        el.parse_weight("")


# ── round trip, including every trap the entry grammar failed ────────────
def test_weight_round_trips():
    r = row(kg=78.2, note="post-run", date="2026-08-20")
    got = el.parse_weight(el.render_weight(r))
    assert got == {"kg": 78.2, "note": "post-run", "date": "2026-08-20"}


def test_weight_note_containing_a_time_survives():
    """Entry grammar: note 'weighed at 6:50 before food' lost the 6:50 AND re-stamped
    the timestamp to 06:50 — two fields corrupted by one edit."""
    r = row(kg=79.4, note="weighed at 6:50 before food", date="2026-08-22")
    got = el.parse_weight(el.render_weight(r))
    assert got["note"] == "weighed at 6:50 before food"
    assert "measured_at" not in got and "time" not in got


def test_weight_note_starting_with_a_number_survives():
    r = row(kg=80.0, note="80 was the goal", date="2026-08-22")
    assert el.parse_weight(el.render_weight(r))["note"] == "80 was the goal"


def test_weight_with_no_note_round_trips_to_empty():
    r = row(kg=78.2, note=None, date="2026-08-27")
    assert el.parse_weight(el.render_weight(r))["note"] == ""


def test_weight_rejects_an_implausible_value():
    with pytest.raises(ParseError, match="plausible weight"):
        el.parse_weight("900")


def test_food_round_trips():
    r = row(description="oatmeal with berries", kcal=350, date="2026-08-20", ate_at=1787223943)
    got = el.parse_food(el.render_food(r))
    assert got["description"] == "oatmeal with berries"
    assert got["kcal"] == 350
    assert got["date"] == "2026-08-20"
    assert ":" in got["time"]


def test_a_numeric_only_food_description_stays_editable():
    """Entry grammar rejected this outright via its numeric-only guard, making the
    row permanently uneditable."""
    r = row(description="750", kcal=350, date="2026-08-20", ate_at=1787223943)
    assert el.parse_food(el.render_food(r))["description"] == "750"


def test_a_food_description_ending_in_a_number_survives():
    r = row(description="coffee 2", kcal=5, date="2026-08-20", ate_at=1787223943)
    got = el.parse_food(el.render_food(r))
    assert (got["description"], got["kcal"]) == ("coffee 2", 5)


def test_food_rejects_a_bad_time():
    with pytest.raises(ParseError, match="not a time"):
        el.parse_food("toast | 100 | 2026-08-20 | 99:99")


def test_expense_round_trips():
    r = row(amount=12.4, description="restaurant tip", category="other", date="2026-08-20")
    got = el.parse_expense(el.render_expense(r))
    assert got == {
        "amount": 12.4,
        "description": "restaurant tip",
        "category": "other",
        "date": "2026-08-20",
    }


def test_expense_description_containing_a_category_slug_survives():
    """Entry grammar: '84.10 lunch at grocery store restaurant' became
    category='grocery', description='lunch at store restaurant'."""
    r = row(
        amount=84.1,
        description="lunch at grocery store",
        category="restaurant",
        date="2026-08-20",
    )
    got = el.parse_expense(el.render_expense(r))
    assert got["description"] == "lunch at grocery store"
    assert got["category"] == "restaurant"


def test_expense_description_containing_a_time_survives():
    """Unfixable by field ordering in the entry grammar — the token is consumed
    wherever it appears."""
    r = row(
        amount=60.0,
        description="dinner 19:30 reservation",
        category="restaurant",
        date="2026-08-20",
    )
    assert (
        el.parse_expense(el.render_expense(r))["description"] == "dinner 19:30 reservation"
    )


def test_a_refund_round_trips():
    r = row(amount=-24.99, description="returned shoes", category="grocery", date="2026-08-20")
    assert el.parse_expense(el.render_expense(r))["amount"] == -24.99


def test_expense_rejects_a_zero_amount():
    with pytest.raises(ParseError, match="non-zero"):
        el.parse_expense("0 | lunch | restaurant")


def test_expense_rejects_an_unknown_category():
    with pytest.raises(ParseError, match="not a category"):
        el.parse_expense("12.40 | lunch | pizza")


def test_expense_accepts_a_formatted_amount():
    assert el.parse_expense("$1,240.50 | rent | housing")["amount"] == 1240.5


def test_recurring_round_trips():
    r = row(name="Transit Pass", cost=120.0, cycle="annually", category="transport")
    got = el.parse_recurring(el.render_recurring(r))
    assert got == {
        "cost": 120.0,
        "name": "Transit Pass",
        "category": "transport",
        "cycle": "annually",
    }


def test_a_recurring_name_containing_annually_survives():
    """The worst entry-grammar case: the keyword was consumed out of the name AND it
    overwrote the cycle, and because the write path upserted by name the mangled
    result INSERTED a second row instead of editing the first."""
    r = row(name="Insurance billed annually", cost=88.0, cycle="monthly", category="other")
    got = el.parse_recurring(el.render_recurring(r))
    assert got["name"] == "Insurance billed annually"
    assert got["cycle"] == "monthly"


def test_a_recurring_name_containing_monthly_in_any_case_survives():
    r = row(name="Monthly Transit Pass", cost=120.0, cycle="annually", category="transport")
    got = el.parse_recurring(el.render_recurring(r))
    assert got["name"] == "Monthly Transit Pass"
    assert got["cycle"] == "annually"


def test_a_recurring_name_that_is_only_a_keyword_survives():
    """Entry grammar raised 'give it a name' — the row could not be edited at all."""
    r = row(name="Annually", cost=10.0, cycle="monthly", category="other")
    assert el.parse_recurring(el.render_recurring(r))["name"] == "Annually"


def test_a_recurring_name_containing_a_category_slug_survives():
    r = row(name="grocery box", cost=60.0, cycle="monthly", category="grocery")
    got = el.parse_recurring(el.render_recurring(r))
    assert got["name"] == "grocery box"
    assert got["category"] == "grocery"


def test_recurring_rejects_a_nonpositive_cost():
    with pytest.raises(ParseError, match="positive"):
        el.parse_recurring("0 | Streaming | subscriptions | monthly")


def test_recurring_rejects_an_unknown_cycle():
    with pytest.raises(ParseError, match="cycle must be"):
        el.parse_recurring("9.99 | Streaming | subscriptions | weekly")


def test_recurring_cycle_is_case_insensitive():
    assert el.parse_recurring("9.99 | S | subscriptions | Monthly")["cycle"] == "monthly"


# ── the property, stated once ────────────────────────────────────────────
HOSTILE = [
    ("weight", el.render_weight, el.parse_weight,
     row(kg=78.2, note="6:50 grocery monthly annually | odd", date="2026-08-27")),
    ("expense", el.render_expense, el.parse_expense,
     row(amount=-1234.5, description="19:30 grocery restaurant monthly | odd",
         category="housing", date="2026-01-02")),
    ("recurring", el.render_recurring, el.parse_recurring,
     row(name="Annually monthly grocery | odd", cost=5.0, cycle="annually",
         category="education")),
]


@pytest.mark.parametrize("name,render,parse,r", HOSTILE, ids=[h[0] for h in HOSTILE])
def test_every_field_survives_a_line_stuffed_with_every_trap_token(name, render, parse, r):
    """One row per entity carrying every hazard at once: a time, three category
    slugs, both cycle keywords and a literal pipe."""
    got = parse(render(r))
    for key, value in r.items():
        if key in got:
            assert got[key] == value, f"{name}.{key} did not survive"


def test_the_edit_grammar_rejects_a_decimal_comma_too():
    """An edit is exactly where someone retypes an amount, so the same 100x trap
    applies. Both grammars share one amount parser."""
    with pytest.raises(ParseError, match="use a dot for decimals"):
        el.parse_expense("12,40 | lunch | restaurant")


def test_the_edit_grammar_still_accepts_thousands_separators():
    assert el.parse_expense("$1,240.50 | rent | housing")["amount"] == 1240.5
