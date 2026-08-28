import sqlite3

import pytest

from daybook.db import SCHEMA_VERSION, TABLES, connect, ensure_schema


def _tables(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return {r["name"] for r in rows}


def test_creates_exactly_the_six_tables(db):
    assert _tables(db) == set(TABLES)
    assert len(TABLES) == 6


def test_rows_are_mappings(db):
    db.execute("INSERT INTO weight (date, measured_at, kg) VALUES ('2026-08-27', 100, 78.2)")
    row = db.execute("SELECT * FROM weight").fetchone()
    assert row["kg"] == 78.2
    assert row["note"] is None


def test_journal_mode_is_delete_not_wal(db):
    mode = db.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "delete"


def test_foreign_keys_enforced(db):
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_user_version_stamped(db):
    assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_ensure_schema_is_idempotent(tmp_path):
    conn = connect(tmp_path / "t.db")
    ensure_schema(conn)
    conn.execute("INSERT INTO weight (date, measured_at, kg) VALUES ('2026-08-27', 1, 70.0)")
    ensure_schema(conn)
    assert conn.execute("SELECT count(*) FROM weight").fetchone()[0] == 1
    conn.close()


def test_connect_creates_missing_parent_directories(tmp_path):
    conn = connect(tmp_path / "deep" / "nested" / "d.db")
    ensure_schema(conn)
    assert (tmp_path / "deep" / "nested" / "d.db").exists()
    conn.close()


def test_budget_month_name_unique(db):
    db.execute(
        "INSERT INTO budget (month, name, category, amount, source)"
        " VALUES ('2026-08', 'Groceries', 'grocery', 500, 'manual')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO budget (month, name, category, amount, source)"
            " VALUES ('2026-08', 'Groceries', 'grocery', 600, 'manual')"
        )


def test_recurring_name_unique(db):
    db.execute(
        "INSERT INTO recurring (name, category, cost, cycle, monthly_cost)"
        " VALUES ('streaming', 'subscriptions', 20.99, 'monthly', 20.99)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO recurring (name, category, cost, cycle, monthly_cost)"
            " VALUES ('streaming', 'subscriptions', 9.99, 'monthly', 9.99)"
        )
