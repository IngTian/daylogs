"""Readers and navigation helpers the tests need and the app does not.

`money.list_expenses` used to serve this purpose, but it had no non-test caller
and it filtered by `date LIKE 'YYYY-MM-%'` — the month-filtering pattern the
horizon invariant forbids. Keeping it in the app made a test convenience look
load-bearing, so it lives here instead.

Navigation helpers say where they are going rather than relying on where the app
opens. Money's tests have always done this, which is why reordering the tabs cost
them nothing and cost the body-adjacent tests eighty-five failures.
"""

from __future__ import annotations

import sqlite3


def all_expenses(conn) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM expense ORDER BY date DESC, id DESC"))


async def go_money(pilot, app):
    """Switch to the Money tab and hand back the widget."""
    await pilot.press("3")
    await pilot.pause()
    return app.query_one("#money")


async def go_body(pilot, app):
    """Switch to the Body tab and hand back the widget."""
    await pilot.press("2")
    await pilot.pause()
    return app.query_one("#body")


async def go_day(pilot, app):
    """Switch to the Day tab — tab 1, and where the app should open."""
    await pilot.press("1")
    await pilot.pause()
    return app.query_one("#summary")
