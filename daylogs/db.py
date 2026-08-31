"""SQLite connection + schema. Six tables, one idempotent DDL block.

No migration framework: a clean schema starts at version 1, stamped in
PRAGMA user_version so a future change has somewhere to hook.

journal_mode=DELETE is deliberate. WAL's -wal/-shm sidecars can sync
independently of the main file under iCloud Drive and corrupt the database on
the receiving device. daylogs is read-heavy; the write cost is noise.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

TABLES: tuple[str, ...] = (
    "weight",
    "food",
    "expense",
    "recurring",
    "budget",
    "report",
)

_DDL = """
CREATE TABLE IF NOT EXISTS weight (
  id          INTEGER PRIMARY KEY,
  date        TEXT    NOT NULL,
  measured_at INTEGER NOT NULL,
  kg          REAL    NOT NULL,
  note        TEXT
);
CREATE INDEX IF NOT EXISTS ix_weight_date ON weight(date);

CREATE TABLE IF NOT EXISTS food (
  id          INTEGER PRIMARY KEY,
  date        TEXT    NOT NULL,
  ate_at      INTEGER NOT NULL,
  description TEXT    NOT NULL,
  kcal        INTEGER NOT NULL,
  source      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_food_date ON food(date);

CREATE TABLE IF NOT EXISTS expense (
  id          INTEGER PRIMARY KEY,
  date        TEXT    NOT NULL,
  amount      REAL    NOT NULL,
  description TEXT    NOT NULL,
  category    TEXT    NOT NULL,
  note        TEXT,
  created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_expense_date ON expense(date);
CREATE INDEX IF NOT EXISTS ix_expense_category ON expense(category);

CREATE TABLE IF NOT EXISTS recurring (
  id           INTEGER PRIMARY KEY,
  name         TEXT    NOT NULL UNIQUE,
  category     TEXT    NOT NULL,
  cost         REAL    NOT NULL,
  cycle        TEXT    NOT NULL,
  monthly_cost REAL    NOT NULL,
  active       INTEGER NOT NULL DEFAULT 1,
  note         TEXT
);

CREATE TABLE IF NOT EXISTS budget (
  id       INTEGER PRIMARY KEY,
  month    TEXT NOT NULL,
  name     TEXT NOT NULL,
  category TEXT NOT NULL,
  amount   REAL NOT NULL,
  source   TEXT NOT NULL,
  note     TEXT,
  UNIQUE(month, name)
);
CREATE INDEX IF NOT EXISTS ix_budget_month ON budget(month);

CREATE TABLE IF NOT EXISTS report (
  date         TEXT PRIMARY KEY,
  content      TEXT    NOT NULL,
  generated_at INTEGER NOT NULL
);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    """Open (creating parent dirs as needed) in autocommit mode.

    isolation_level=None means writes land without an explicit commit and
    there is never a half-open transaction to reason about — the right trade
    for a single-user local app with no concurrent writers.
    """
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_DDL)
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


def table_names(conn: sqlite3.Connection) -> list[str]:
    """The user's tables, in a stable order.

    Asked of the database rather than kept as a list beside `_DDL`, so a table
    added later cannot be silently left out of an export. `sqlite_%` names are
    SQLite's own bookkeeping (`sqlite_sequence` and friends) — implementation
    detail, not anybody's data.
    """
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    )
    return [r[0] for r in rows]
