"""A payment that covers several months, counted in the months it covers.

The budget side has always prorated: `roll_month_budgets` writes `monthly_cost`, so a
240.00-a-year subscription gets a 20.00 line every month. The spend side summed the raw
charge, so the renewal month read 240.00 against a 20.00 cap — 12x over — and the other
eleven read a 20.00 saving. It nets out over a year and no single month is ever right,
which is a problem for a tab whose whole question is "am I inside the budget this month".

`#N` on an expense line is how you say a payment covers N months. The charge is stored once,
at its real amount and date — export and the expenses pane both still show the 240.00 that
left the account — and every *total* counts amount/N in each covered month.
"""

import datetime as dt
import sqlite3
import tempfile
from pathlib import Path

import pytest
from helpers import go_money

from daylogs import db as dbmod
from daylogs.horizon import resolve
from daylogs.money import (
    MoneyError,
    _covered_months,
    add_expense,
    list_budget,
    roll_month_budgets,
    summarize_month,
    summarize_span,
    update_expense,
    upsert_recurring,
)
from daylogs.parse import ParseError, parse_expense, render_expense

NOW = dt.datetime(2026, 9, 14, 10, 0)
SLUGS = frozenset({"subscriptions", "grocery", "other", "restaurant"})


def _span(anchor="2027-12-31", horizon="all"):
    return resolve(horizon, anchor=anchor)


def _spent(conn, month, category="subscriptions"):
    s = summarize_month(conn, month=month, today="2026-09-30")
    cat = next((c for c in s.by_category if c.category == category), None)
    return cat.spent if cat else None


# ── the migration ────────────────────────────────────────────────────────
def test_an_existing_database_gains_the_column_without_losing_rows():
    """`CREATE TABLE IF NOT EXISTS` cannot add a column, so a database made before this
    column existed would break every reader that selects it. `_ADD_COLUMNS` ALTERs it in,
    guarded by `PRAGMA table_info` so it is safe on every open.

    Built by hand as a v2 `expense` table rather than by an older daylogs, because that is
    the shape the guard has to cope with and there is no other way to get one.
    """
    path = Path(tempfile.mkdtemp()) / "old.db"
    raw = sqlite3.connect(path)
    raw.execute(
        "CREATE TABLE expense (id INTEGER PRIMARY KEY, date TEXT NOT NULL,"
        " amount REAL NOT NULL, description TEXT NOT NULL, category TEXT NOT NULL,"
        " note TEXT, created_at INTEGER NOT NULL)"
    )
    raw.execute(
        "INSERT INTO expense (date, amount, description, category, created_at)"
        " VALUES ('2026-01-01', 9.99, 'from before', 'other', 0)"
    )
    raw.commit()
    raw.close()

    conn = dbmod.connect(path)
    dbmod.ensure_schema(conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(expense)")]
    assert "prepaid_months" in cols
    row = conn.execute("SELECT description, amount, prepaid_months FROM expense").fetchone()
    assert (row["description"], row["amount"], row["prepaid_months"]) == ("from before", 9.99, None)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == dbmod.SCHEMA_VERSION


def test_ensure_schema_is_still_idempotent():
    """It runs on every open, so a second ALTER would raise "duplicate column name"."""
    path = Path(tempfile.mkdtemp()) / "t.db"
    conn = dbmod.connect(path)
    for _ in range(3):
        dbmod.ensure_schema(conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(expense)")]
    assert cols.count("prepaid_months") == 1


# ── the grammar ──────────────────────────────────────────────────────────
def test_hash_n_on_an_expense_says_how_many_months_it_covers():
    r = parse_expense("240 Insurance !subscriptions #12", now=NOW, known_slugs=SLUGS)
    assert (r.amount, r.prepaid_months) == (240.0, 12)


def test_an_ordinary_expense_has_no_marker():
    r = parse_expense("12.40 lunch !restaurant", now=NOW, known_slugs=SLUGS)
    assert r.prepaid_months is None


@pytest.mark.parametrize(
    "line,match",
    [
        ("240 x !other #1", "at least 2"),
        ("240 x !other #0", "at least 2"),
        ("240 x !other #abc", "number of months"),
        ("240 x !other #999", "not a prepayment"),
    ],
)
def test_a_nonsense_month_count_is_rejected(line, match):
    """`#1` is rejected rather than accepted: a payment covering one month *is* an ordinary
    expense, and storing the marker anyway would put a second representation of the plain
    case into every reader that has to prorate."""
    with pytest.raises(ParseError, match=match):
        parse_expense(line, now=NOW, known_slugs=SLUGS)


def test_the_marker_round_trips_through_the_edit_prefill(db):
    """`parse(render(row)) == row` is the property the whole grammar is held to, and the
    marker is displayed in the pane, so it has to be editable — including clearable."""
    add_expense(db, amount=240.0, description="Insurance", category="subscriptions",
                date="2026-09-14", prepaid_months=12)
    row = db.execute("SELECT * FROM expense").fetchone()
    line = render_expense(row)
    assert "#12" in line, line
    back = parse_expense(line, now=NOW, known_slugs=SLUGS)
    assert (back.amount, back.category, back.date, back.prepaid_months) == (
        240.0, "subscriptions", "2026-09-14", 12,
    )


def test_dropping_the_hash_from_an_edit_makes_it_an_ordinary_expense(db):
    """The same "submitted line is authoritative" rule the note follows. 0 is the clearing
    value because `update_expense` drops None to tell "not mentioned" from "set to
    nothing", and the grammar can never produce `#0`."""
    add_expense(db, amount=240.0, description="Insurance", category="subscriptions",
                date="2026-09-14", prepaid_months=12)
    row_id = db.execute("SELECT id FROM expense").fetchone()["id"]
    update_expense(db, row_id, prepaid_months=0)
    assert db.execute("SELECT prepaid_months FROM expense").fetchone()[0] is None


def test_the_data_layer_guards_the_column_too():
    """`add_expense` is called by tests, `__main__` and summary as well as by the prompt, so
    the grammar's check is not the only door."""
    conn = dbmod.connect(Path(tempfile.mkdtemp()) / "t.db")
    dbmod.ensure_schema(conn)
    with pytest.raises(MoneyError, match="between 2 and 120"):
        add_expense(conn, amount=240.0, description="x", category="other",
                    date="2026-09-14", prepaid_months=1)


# ── which months a payment covers ────────────────────────────────────────
def test_coverage_starts_in_the_payment_s_own_month_and_wraps_the_year():
    assert _covered_months("2026-09-14", 3) == ["2026-09", "2026-10", "2026-11"]
    assert _covered_months("2026-11-01", 4) == ["2026-11", "2026-12", "2027-01", "2027-02"]
    assert len(_covered_months("2026-09-14", 12)) == 12
    assert _covered_months("2026-09-14", 12)[-1] == "2027-08"


# ── the arithmetic ───────────────────────────────────────────────────────
def test_the_renewal_month_is_no_longer_over_its_cap(db):
    """The defect, stated as the numbers it produced: 240.00 against a 20.00 cap."""
    upsert_recurring(db, name="Insurance", cost=240.0, cycle="annually", category="subscriptions")
    roll_month_budgets(db, month="2026-09")
    add_expense(db, amount=240.0, description="Insurance renewal", category="subscriptions",
                date="2026-09-14", prepaid_months=12)
    s = summarize_month(db, month="2026-09", today="2026-09-30")
    cat = next(c for c in s.by_category if c.category == "subscriptions")
    assert (cat.budget, cat.spent, cat.delta) == (20.0, 20.0, 0.0)
    assert list_budget(db, month="2026-09")[0]["amount"] == 20.0


def test_every_covered_month_carries_its_share(db):
    add_expense(db, amount=240.0, description="Insurance", category="subscriptions",
                date="2026-09-14", prepaid_months=12)
    for month in ("2026-09", "2026-12", "2027-08"):
        assert _spent(db, month) == 20.0, month


def test_the_month_after_coverage_ends_carries_nothing(db):
    """Twelve months from September is August, so the next September is a new year's
    problem — otherwise the charge would prorate forever."""
    add_expense(db, amount=240.0, description="Insurance", category="subscriptions",
                date="2026-09-14", prepaid_months=12)
    assert _spent(db, "2027-09") is None
    assert _spent(db, "2026-08") is None, "and nothing before it was paid, either"


def test_the_shares_add_back_to_the_amount_actually_paid(db):
    """No cent drift: the shares are summed unrounded and only the total is rounded, so a
    240.01 charge over 12 months does not lose a penny a month. Over all time the tab shows
    exactly what left the account."""
    add_expense(db, amount=240.01, description="Insurance", category="subscriptions",
                date="2026-09-14", prepaid_months=12)
    s = summarize_span(db, span=_span(), today="2027-12-31")
    cat = next(c for c in s.by_category if c.category == "subscriptions")
    assert cat.spent == 240.01


def test_an_ordinary_expense_is_untouched(db):
    """The whole change hangs off `prepaid_months IS NULL`, so the common case has to be
    provably unaffected — including a refund, which is a negative amount."""
    add_expense(db, amount=52.10, description="market", category="grocery", date="2026-09-03")
    add_expense(db, amount=-12.00, description="returned", category="grocery", date="2026-09-04")
    assert _spent(db, "2026-09", "grocery") == 40.10


def test_a_prepayment_and_an_ordinary_charge_in_one_category_both_count(db):
    """They come from two different queries now — one SQL sum, one Python spread — so the
    seam between them is worth an assertion."""
    add_expense(db, amount=240.0, description="Insurance", category="subscriptions",
                date="2026-09-14", prepaid_months=12)
    add_expense(db, amount=9.99, description="Streaming", category="subscriptions",
                date="2026-09-20")
    assert _spent(db, "2026-09") == 29.99


def test_the_six_month_sparkline_prorates_too(db):
    """The bar beside the number has to tell the same story. A single annual charge drew one
    spike in an otherwise flat six months, which reads as a spending event rather than as
    the year's subscription.

    The window here is 2026-04..2026-09 and coverage starts in May, so the first month is a
    real 0 — asserted rather than smoothed over, because it is what proves the spread has a
    *start* and is not just filling every month it can reach.
    """
    add_expense(db, amount=600.0, description="Insurance", category="subscriptions",
                date="2026-05-01", prepaid_months=12)
    s = summarize_month(db, month="2026-09", today="2026-09-30")
    cat = next(c for c in s.by_category if c.category == "subscriptions")
    assert cat.history == [0.0, 50.0, 50.0, 50.0, 50.0, 50.0], (
        f"a level 50 from May, nothing in April, no spike: {cat.history}"
    )


# ── on screen ────────────────────────────────────────────────────────────
async def test_the_expenses_pane_shows_the_real_charge_with_its_marker(make_app, db, type_into):
    """The pane lists payments, so it shows the 240.00 that left the account — a list that
    quietly showed a twelfth would be lying about the row. `#12` is what stops that reading
    as a contradiction of the header, which counts the same payment at 20.00."""
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        tab = await go_money(pilot, app)
        await pilot.press("e")
        await type_into(pilot, "240 Insurance !subscriptions #12")
        await pilot.press("enter")
        await pilot.pause()
        while tab.view.pane != "expenses":
            await pilot.press("tab")
            await pilot.pause()
        table = app.query_one("#money-table")
        cells = [str(c) for k in table.rows for c in table.get_row(k)]
    assert any("Insurance #12" in c for c in cells), cells
    assert any("240.00" in c for c in cells), f"the pane must show what was paid: {cells}"
    row = db.execute("SELECT amount, prepaid_months FROM expense").fetchone()
    assert (row["amount"], row["prepaid_months"]) == (240.0, 12)
