"""Getting your data out.

A backup you can only restore into daylogs is a weaker promise than an export you
can open anywhere, so these tests care about two things: that the export is
*complete* (every table, every column, no silent omissions) and that what comes
back out equals what went in.
"""

import csv
import datetime as dt

import pytest

from daylogs.body import add_food, add_weight
from daylogs.db import table_names
from daylogs.export import export_csv
from daylogs.money import add_expense, upsert_budget, upsert_recurring
from daylogs.summary import upsert_report

TODAY = dt.date(2026, 8, 30)


def _rows(path):
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _seed(db):
    add_weight(db, kg=78.2, date="2026-08-27", at=1787000000, note="post-run")
    add_weight(db, kg=78.0, date="2026-08-28", at=1787086400, note="")
    add_food(db, description="chicken salad", kcal=610, source="labeled",
             date="2026-08-27", at=1787030000)
    add_expense(db, amount=12.40, description="lunch", category="restaurant",
                date="2026-08-27", note="paid cash")
    add_expense(db, amount=-24.99, description="returned shoes", category="grocery",
                date="2026-08-28")
    upsert_recurring(db, name="Streaming", cost=20.99, cycle="monthly",
                     category="subscriptions")
    upsert_budget(db, month="2026-08", name="Grocery", category="grocery",
                  amount=500.0, source="manual")
    upsert_report(db, date="2026-08-27", content="a short read")


# ── completeness ──────────────────────────────────────────────────────────


def test_every_table_in_the_schema_gets_a_file(db, tmp_path):
    """Derived from the schema, not from a hand-kept list.

    A list would be one more thing to remember when a table is added, and
    forgetting it means an export that looks complete and silently is not.
    """
    out = export_csv(db, tmp_path / "out", today=TODAY)
    written = {p.stem for p in out}
    assert written == set(table_names(db)), f"exported {written}, schema has {set(table_names(db))}"
    assert written, "no tables were exported at all"


def test_the_header_of_each_file_is_that_table_s_columns(db, tmp_path):
    export_csv(db, tmp_path / "out", today=TODAY)
    for table in table_names(db):
        cols = [r[1] for r in db.execute(f"PRAGMA table_info({table})")]
        with (tmp_path / "out" / f"daylogs-export-{TODAY}" / f"{table}.csv").open() as fh:
            header = next(csv.reader(fh))
        assert header == cols, f"{table}: header {header} != columns {cols}"


def test_an_empty_table_still_gets_a_file_with_its_header(db, tmp_path):
    """An absent file is ambiguous — no rows, or a bug? A header-only file says
    'this table exists and is empty' without the reader having to guess."""
    out = export_csv(db, tmp_path / "out", today=TODAY)
    weight = next(p for p in out if p.stem == "weight")
    assert weight.exists()
    assert _rows(weight) == []
    with weight.open() as fh:
        assert next(csv.reader(fh)) == ["id", "date", "measured_at", "kg", "note"]


# ── fidelity ──────────────────────────────────────────────────────────────


def test_rows_come_back_out_as_they_went_in(db, tmp_path):
    _seed(db)
    export_csv(db, tmp_path / "out", today=TODAY)
    d = tmp_path / "out" / f"daylogs-export-{TODAY}"

    weight = _rows(d / "weight.csv")
    assert [r["kg"] for r in weight] == ["78.2", "78.0"]
    assert [r["date"] for r in weight] == ["2026-08-27", "2026-08-28"]
    assert weight[0]["note"] == "post-run"

    expense = _rows(d / "expense.csv")
    assert [r["amount"] for r in expense] == ["12.4", "-24.99"], "a refund must survive"
    assert [r["category"] for r in expense] == ["restaurant", "grocery"]
    assert expense[0]["note"] == "paid cash"

    food = _rows(d / "food.csv")
    assert (food[0]["description"], food[0]["kcal"]) == ("chicken salad", "610")

    assert _rows(d / "recurring.csv")[0]["name"] == "Streaming"
    assert _rows(d / "budget.csv")[0]["month"] == "2026-08"
    assert _rows(d / "report.csv")[0]["content"] == "a short read"


def test_row_counts_match_the_database(db, tmp_path):
    _seed(db)
    out = export_csv(db, tmp_path / "out", today=TODAY)
    for path in out:
        in_db = db.execute(f"SELECT count(*) FROM {path.stem}").fetchone()[0]
        got = len(_rows(path))
        assert got == in_db, f"{path.stem}: {got} rows exported, {in_db} in the database"


def test_a_null_note_exports_as_an_empty_field(db, tmp_path):
    """CSV cannot distinguish NULL from empty, and that is the documented cost of
    choosing it. What must not happen is the string 'None' landing in the file."""
    add_expense(db, amount=5.0, description="coffee", category="restaurant",
                date="2026-08-27")
    export_csv(db, tmp_path / "out", today=TODAY)
    row = _rows(tmp_path / "out" / f"daylogs-export-{TODAY}" / "expense.csv")[0]
    assert row["note"] == "", f"a NULL note exported as {row['note']!r}"


def test_a_description_with_a_comma_and_a_quote_survives(db, tmp_path):
    """The reason for using the csv module rather than joining with commas."""
    nasty = 'dinner, "the good place", 2 people'
    add_expense(db, amount=80.0, description=nasty, category="restaurant",
                date="2026-08-27")
    export_csv(db, tmp_path / "out", today=TODAY)
    row = _rows(tmp_path / "out" / f"daylogs-export-{TODAY}" / "expense.csv")[0]
    assert row["description"] == nasty


def test_a_report_containing_newlines_survives(db, tmp_path):
    """Summaries are multi-line markdown, which is exactly what breaks a
    line-per-row reader that was written by hand."""
    content = "## Body\n\nWeight is down 0.4 kg.\n\n## Money\n\nInside budget.\n"
    upsert_report(db, date="2026-08-29", content=content)
    export_csv(db, tmp_path / "out", today=TODAY)
    rows = _rows(tmp_path / "out" / f"daylogs-export-{TODAY}" / "report.csv")
    assert len(rows) == 1, f"a multi-line report split into {len(rows)} rows"
    assert rows[0]["content"] == content


# ── mechanics ─────────────────────────────────────────────────────────────


def test_rows_are_ordered_deterministically(db, tmp_path):
    """Two exports of an unchanged database must be byte-identical, or a diff of
    two snapshots is noise."""
    _seed(db)
    first = (tmp_path / "a")
    second = (tmp_path / "b")
    export_csv(db, first, today=TODAY)
    export_csv(db, second, today=TODAY)
    for table in table_names(db):
        a = (first / f"daylogs-export-{TODAY}" / f"{table}.csv").read_bytes()
        b = (second / f"daylogs-export-{TODAY}" / f"{table}.csv").read_bytes()
        assert a == b, f"{table}.csv differed between two exports of the same data"


def test_the_destination_is_created_and_dated(db, tmp_path):
    dest = tmp_path / "nested" / "does-not-exist"
    out = export_csv(db, dest, today=TODAY)
    assert out, "nothing was written"
    assert out[0].parent == dest / f"daylogs-export-{TODAY}"
    assert out[0].parent.is_dir()


def test_re_exporting_the_same_day_replaces_the_files(db, tmp_path):
    _seed(db)
    export_csv(db, tmp_path / "out", today=TODAY)
    path = tmp_path / "out" / f"daylogs-export-{TODAY}" / "expense.csv"
    assert len(_rows(path)) == 2
    db.execute("DELETE FROM expense WHERE description = 'lunch'")
    export_csv(db, tmp_path / "out", today=TODAY)
    assert len(_rows(path)) == 1, "the second export did not replace the first"


def test_no_internal_table_reaches_the_export(db, tmp_path):
    """Kept as a guard on the export's own output, but note it cannot fail today:
    daylogs's tables use INTEGER PRIMARY KEY rather than AUTOINCREMENT, so
    `sqlite_sequence` is never created and there is nothing here to filter. The
    filter itself is tested where it lives, against a database that does have one
    — see test_db.py::test_table_names_hides_sqlite_internals.
    """
    out = export_csv(db, tmp_path / "out", today=TODAY)
    assert not [p for p in out if p.stem.startswith("sqlite_")], (
        f"exported an internal table: {[p.stem for p in out]}"
    )


@pytest.mark.parametrize("table", ["weight", "food", "expense", "recurring", "budget", "report"])
def test_each_expected_table_is_present_by_name(db, tmp_path, table):
    """Belt and braces against the schema-derived list quietly returning fewer
    tables than the app actually has."""
    out = export_csv(db, tmp_path / "out", today=TODAY)
    assert table in {p.stem for p in out}
