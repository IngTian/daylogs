"""Readers the tests need and the app does not.

`money.list_expenses` used to serve this purpose, but it had no non-test caller
and it filtered by `date LIKE 'YYYY-MM-%'` — the month-filtering pattern the
horizon invariant forbids. Keeping it in the app made a test convenience look
load-bearing, so it lives here instead.
"""

from __future__ import annotations

import sqlite3


def all_expenses(conn) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM expense ORDER BY date DESC, id DESC"))
