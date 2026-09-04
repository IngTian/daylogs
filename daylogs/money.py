"""Money: expenses, recurring items, budgets, and month arithmetic.

Expenses only. `amount` is positive for a spend and negative for a refund;
there is no income concept, no account, and no balance. That single decision
is what removes a double-entry ledger, a family of reserve helpers, and
end-of-month cash projection — most of the volume of a finance module, and
rather more than that of its confusion.
"""

from __future__ import annotations

import calendar
import datetime as dt
import re
import sqlite3
import time
from dataclasses import dataclass, field

from daylogs.categories import slugs
from daylogs.horizon import Span

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_LIMIT_CAP = 5000
CYCLES = frozenset({"monthly", "annually"})
HISTORY_MONTHS = 6
_BUDGET_SOURCES = frozenset({"manual", "recurring"})


class MoneyError(ValueError):
    pass


# ── validators (shared with summary.py and __main__.py) ──────────────────
def check_date(date: str) -> str:
    if not _DATE_RE.match(date):
        raise MoneyError(f"date {date!r} must be YYYY-MM-DD")
    try:
        dt.date.fromisoformat(date)
    except ValueError as e:
        raise MoneyError(f"date {date!r} is not a real date") from e
    return date


def check_month(month: str) -> str:
    if not _MONTH_RE.match(month):
        raise MoneyError(f"month {month!r} must be YYYY-MM")
    try:
        dt.date.fromisoformat(f"{month}-01")
    except ValueError as e:
        raise MoneyError(f"month {month!r} is not a real year-month") from e
    return month


def check_category(category: str, cfg=None) -> str:
    if category not in slugs(cfg):
        raise MoneyError(
            f"category {category!r} is not known; add it to config.toml as a "
            "[[category]] block if you want it"
        )
    return category


def _now() -> int:
    return int(time.time())


def months_ending(month: str, n: int) -> list[str]:
    """n YYYY-MM strings ending at `month` inclusive, ascending."""
    check_month(month)
    y, m = int(month[:4]), int(month[5:7])
    out: list[str] = []
    for back in range(n - 1, -1, -1):
        total = y * 12 + (m - 1) - back
        yy, mm = divmod(total, 12)
        out.append(f"{yy:04d}-{mm + 1:02d}")
    return out


# ── expenses ─────────────────────────────────────────────────────────────
def add_expense(
    conn,
    *,
    amount: float,
    description: str,
    category: str,
    date: str,
    note: str | None = None,
    cfg=None,
) -> int:
    if float(amount) == 0:
        raise MoneyError("amount must be non-zero")
    if not description.strip():
        raise MoneyError("description must be non-empty")
    cur = conn.execute(
        "INSERT INTO expense (date, amount, description, category, note, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            check_date(date),
            float(amount),
            description.strip(),
            check_category(category, cfg),
            note or None,
            _now(),
        ),
    )
    return int(cur.lastrowid)


def update_expense(conn, id: int, cfg=None, **fields) -> bool:
    fields = {k: v for k, v in fields.items() if v is not None}
    allowed = {"amount", "description", "category", "date", "note"}
    unknown = set(fields) - allowed
    if unknown:
        raise MoneyError(f"cannot update {sorted(unknown)} on expense")
    if not fields:
        return False
    if "date" in fields:
        check_date(fields["date"])
    if "category" in fields:
        check_category(fields["category"], cfg)
    if "amount" in fields and float(fields["amount"]) == 0:
        raise MoneyError("amount must be non-zero")
    sets = ", ".join(f"{k} = ?" for k in fields)
    cur = conn.execute(f"UPDATE expense SET {sets} WHERE id = ?", (*fields.values(), int(id)))
    return cur.rowcount > 0


def delete_expense(conn, id: int) -> dict | None:
    return _delete(conn, "expense", id)


def _delete(conn, table: str, id: int) -> dict | None:
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (int(id),)).fetchone()
    if row is None:
        return None
    conn.execute(f"DELETE FROM {table} WHERE id = ?", (int(id),))
    return dict(row)


# ── recurring ────────────────────────────────────────────────────────────
def monthly_equivalent(cost: float, cycle: str) -> float:
    if cycle not in CYCLES:
        raise MoneyError(f"cycle must be one of {sorted(CYCLES)}")
    return round(float(cost) / 12, 2) if cycle == "annually" else round(float(cost), 2)


def upsert_recurring(
    conn,
    *,
    name: str,
    cost: float,
    cycle: str,
    category: str,
    note: str | None = None,
    active: bool = True,
    cfg=None,
) -> int:
    """Add an item, or update one of the same name.

    `active` applies on **insert only** — it is deliberately absent from the ON CONFLICT
    clause. Pausing is a state you set on purpose with `o`; a re-add is about cost, cycle
    and category, and it arrives through a grammar that cannot express the flag, so
    `active = excluded.active` meant every re-add carried the parameter's `True` default.
    Raising a paused subscription's price un-paused it, and the next roll charged for it
    with nothing on screen connecting the two.

    `note` is still overwritten, which has the same shape and is left alone on purpose:
    the recurring grammar has no `~note`, so that column is unreachable from the UI in
    both directions and fixing one half of an unreachable field would be pretending.
    """
    name = name.strip()
    if not name:
        raise MoneyError("recurring item needs a name")
    if float(cost) <= 0:
        raise MoneyError("recurring cost must be > 0")
    monthly = monthly_equivalent(cost, cycle)
    check_category(category, cfg)
    conn.execute(
        """
        INSERT INTO recurring (name, category, cost, cycle, monthly_cost, active, note)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
          category = excluded.category,
          cost = excluded.cost,
          cycle = excluded.cycle,
          monthly_cost = excluded.monthly_cost,
          note = excluded.note
        """,
        (name, category, float(cost), cycle, monthly, 1 if active else 0, note or None),
    )
    row = conn.execute("SELECT id FROM recurring WHERE name = ?", (name,)).fetchone()
    return int(row["id"])


def list_recurring(conn, *, active_only: bool = False) -> list[sqlite3.Row]:
    sql = "SELECT * FROM recurring"
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY monthly_cost DESC, name ASC"
    return list(conn.execute(sql))


def update_recurring(conn, id: int, cfg=None, **fields) -> bool:
    """Edit a recurring item in place, by id.

    `upsert_recurring` cannot serve as the edit path: it resolves conflicts on
    `name`, so renaming an item matches nothing and INSERTs a second row. Both then
    look active, and the next `roll_month_budgets` writes two budget lines for one
    subscription. Keyed by id, a rename is a rename.

    `monthly_cost` is a stored derived column that `roll_month_budgets` reads, so it
    is recomputed whenever cost or cycle moves. Leaving it stale would put the wrong
    number into next month's budget, a month later, with nothing on screen
    connecting the two.
    """
    fields = {k: v for k, v in fields.items() if v is not None}
    allowed = {"name", "category", "cost", "cycle", "note", "active"}
    unknown = set(fields) - allowed
    if unknown:
        raise MoneyError(f"cannot update {sorted(unknown)} on recurring")
    if not fields:
        return False
    row = conn.execute("SELECT * FROM recurring WHERE id = ?", (int(id),)).fetchone()
    if row is None:
        return False

    if "category" in fields:
        check_category(fields["category"], cfg)
    if "name" in fields:
        name = str(fields["name"]).strip()
        if not name:
            raise MoneyError("a recurring item needs a name")
        # Pre-check rather than letting the UNIQUE(name) constraint raise: the
        # sqlite error names a column, this names the item the user can go fix.
        clash = conn.execute(
            "SELECT id FROM recurring WHERE name = ? AND id != ?", (name, int(id))
        ).fetchone()
        if clash is not None:
            raise MoneyError(f"{name!r} already exists")
        fields["name"] = name

    cost = float(fields.get("cost", row["cost"]))
    cycle = fields.get("cycle", row["cycle"])
    if cost <= 0:
        raise MoneyError("a recurring cost must be positive")
    if "cost" in fields or "cycle" in fields:
        fields["monthly_cost"] = monthly_equivalent(cost, cycle)
    if "active" in fields:
        fields["active"] = 1 if fields["active"] else 0

    sets = ", ".join(f"{k} = ?" for k in fields)
    cur = conn.execute(
        f"UPDATE recurring SET {sets} WHERE id = ?", (*fields.values(), int(id))
    )
    if "name" in fields:
        _rename_rolled_budgets(conn, old=row["name"], new=fields["name"])
    return cur.rowcount > 0


def budget_line(conn, *, month: str, category: str) -> sqlite3.Row | None:
    """The budget row for one category in one month, or None.

    A category can hold more than one line in a month — `budget` is UNIQUE(month, name),
    not (month, category), so a `Rent` and a `Storage` line can both be `housing`. The
    newest wins here, which is the one an edit prefill should show; the pane's own figures
    keep summing all of them, so this is a lookup for editing, not a total.
    """
    check_month(month)
    return conn.execute(
        "SELECT * FROM budget WHERE month = ? AND category = ? ORDER BY id DESC LIMIT 1",
        (month, category),
    ).fetchone()


def _rename_rolled_budgets(conn, *, old: str, new: str) -> None:
    """Carry a recurring item's rename through to the budget lines it produced.

    Budget rows are keyed by `name`, recurring items by `id`, and nothing joined the
    two. So a rename left the old month's line standing and the next `roll_month_budgets`
    added a second line for the same subscription: one 24.99 item became 49.98 of budget,
    permanently, in the single number the Money tab exists to answer.

    Fixed here rather than by reconciling at roll time, because this is the only place
    that knows a rename happened. From the budget table alone an unclaimed line is
    indistinguishable from one whose item was *deleted* — and those want opposite
    treatment: a month you have already paid for keeps its line, and next month's roll
    simply will not include it.

    Only `source='recurring'` rows move. A number you typed by hand is yours; the roll
    has never overwritten one and neither does this.
    """
    if old == new:
        return
    # Drop the old line in any month that already has one under the new name, rather
    # than colliding with UNIQUE(month, name). Such a month has both because it was
    # rolled after the rename — the old row is precisely the duplicate being cleaned up.
    conn.execute(
        "DELETE FROM budget WHERE name = ? AND source = 'recurring'"
        " AND month IN (SELECT month FROM budget WHERE name = ?)",
        (old, new),
    )
    conn.execute(
        "UPDATE budget SET name = ? WHERE name = ? AND source = 'recurring'",
        (new, old),
    )


def delete_recurring(conn, id: int) -> dict | None:
    return _delete(conn, "recurring", id)


# ── budgets ──────────────────────────────────────────────────────────────
def upsert_budget(
    conn,
    *,
    month: str,
    name: str,
    category: str,
    amount: float,
    source: str = "manual",
    note: str | None = None,
    cfg=None,
) -> int:
    name = name.strip()
    if not name:
        raise MoneyError("budget line needs a name")
    if float(amount) < 0:
        raise MoneyError("budget amount must be >= 0")
    if source not in _BUDGET_SOURCES:
        raise MoneyError(f"source must be one of {sorted(_BUDGET_SOURCES)}")
    check_month(month)
    check_category(category, cfg)
    conn.execute(
        """
        INSERT INTO budget (month, name, category, amount, source, note)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(month, name) DO UPDATE SET
          category = excluded.category,
          amount = excluded.amount,
          source = excluded.source,
          note = excluded.note
        """,
        (month, name, category, float(amount), source, note or None),
    )
    row = conn.execute(
        "SELECT id FROM budget WHERE month = ? AND name = ?", (month, name)
    ).fetchone()
    return int(row["id"])


def list_budget(conn, *, month: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM budget WHERE month = ? ORDER BY category ASC, name ASC",
            (check_month(month),),
        )
    )


def pending_roll(conn, *, month: str) -> tuple[int, float]:
    """(count, monthly total) that `roll_month_budgets` would add to `month`.

    Budgets are per-month rows, so a month nobody rolled has none — and the
    header then reads "0.00 budget / 1,234.00 over", which is arithmetically true
    and completely useless. Knowing what a roll *would* produce lets the empty
    state name the fix instead of just reporting a zero.
    """
    check_month(month)
    existing = {r["name"] for r in list_budget(conn, month=month)}
    pending = [r for r in list_recurring(conn, active_only=True) if r["name"] not in existing]
    return len(pending), round(sum(r["monthly_cost"] for r in pending), 2)


def roll_month_budgets(conn, *, month: str, cfg=None) -> int:
    """Create a budget line for each active recurring item that has no line in
    `month` yet, and return how many were created. Never overwrites an
    existing line — if you hand-set a number for a subscription this month,
    the roll leaves it alone."""
    check_month(month)
    existing = {r["name"] for r in list_budget(conn, month=month)}
    created = 0
    for r in list_recurring(conn, active_only=True):
        if r["name"] in existing:
            continue
        upsert_budget(
            conn,
            month=month,
            name=r["name"],
            category=r["category"],
            amount=r["monthly_cost"],
            source="recurring",
            cfg=cfg,
        )
        created += 1
    return created


# ── month summary ────────────────────────────────────────────────────────
@dataclass
class CategorySpend:
    category: str
    budget: float
    spent: float
    delta: float
    history: list[float] = field(default_factory=list)


@dataclass
class MonthSummary:
    month: str
    total_spent: float
    total_budget: float
    remaining: float
    by_category: list[CategorySpend]
    top_expenses: list[sqlite3.Row]
    day_of_month: int
    days_in_month: int
    over_budget: list[CategorySpend]
    under_budget_remaining: list[CategorySpend]


def month_span(month: str) -> Span:
    """The whole of one calendar month, as a Span."""
    check_month(month)
    y, m = int(month[:4]), int(month[5:7])
    last = calendar.monthrange(y, m)[1]
    return Span(horizon="MTD", start=f"{month}-01", end=f"{month}-{last:02d}")


def summarize_month(conn, *, month: str, today: str | None = None, cfg=None) -> MonthSummary:
    """One whole calendar month. A thin wrapper over summarize_span, so the tests
    written against this signature keep guarding the arithmetic unchanged."""
    return summarize_span(conn, span=month_span(month), today=today, cfg=cfg)


def summarize_span(
    conn, *, span: Span | None, today: str | None = None, cfg=None
) -> MonthSummary:
    """Per-category budget vs spent over an arbitrary date span, plus totals, the
    top five spends, and a six-month per-category history.

    `span=None` means all time. Spend is filtered by **date**, so a one-week
    horizon really covers seven days rather than the whole month. **Budget over a
    span is the sum of the calendar months it touches** — a span containing an
    unbudgeted month is honestly under-budgeted, not an error.

    Query count is constant regardless of span width: one for the history window,
    one for span spend, one for budgets, one for the top five. The obvious
    implementation issues one query per month in the span.
    """
    months = span.months() if span is not None else []
    anchor = months[-1] if months else _latest_expense_month(conn)
    window = months_ending(anchor, HISTORY_MONTHS) if anchor else []

    history: dict[str, list[float]] = {}
    if window:
        rows = conn.execute(
            """
            SELECT substr(date, 1, 7) AS ym, category, SUM(amount) AS total
            FROM expense
            WHERE date >= ? AND date < ?
            GROUP BY ym, category
            """,
            (f"{window[0]}-01", _month_after(window[-1])),
        ).fetchall()
        idx_of = {ym: i for i, ym in enumerate(window)}
        for r in rows:
            i = idx_of.get(r["ym"])
            if i is None:
                continue
            hist = history.setdefault(r["category"], [0.0] * HISTORY_MONTHS)
            hist[i] = round(float(r["total"]), 2)

    spent_by_cat = _spent_by_category(conn, span)
    budget_by_cat = _budget_by_category(conn, months)

    by_category: list[CategorySpend] = []
    for cat in sorted(set(budget_by_cat) | set(spent_by_cat)):
        budget = budget_by_cat.get(cat, 0.0)
        spent = spent_by_cat.get(cat, 0.0)
        by_category.append(
            CategorySpend(
                category=cat,
                budget=budget,
                spent=spent,
                delta=round(budget - spent, 2),
                history=history.get(cat, [0.0] * HISTORY_MONTHS),
            )
        )

    total_budget = round(sum(c.budget for c in by_category), 2)
    total_spent = round(sum(c.spent for c in by_category), 2)

    where, args = _span_where(span)
    top_expenses = list(
        conn.execute(
            f"SELECT * FROM expense WHERE amount > 0{where}"
            " ORDER BY amount DESC, id DESC LIMIT 5",
            args,
        )
    )

    # Burn-against-elapsed only means something for a single month; across a
    # quarter it would invite a false read, so the caller is told to hide it.
    day, total_days = _calendar_progress(months[0], today) if len(months) == 1 else (0, 0)

    return MonthSummary(
        month=months[-1] if months else "all",
        total_spent=total_spent,
        total_budget=total_budget,
        remaining=round(total_budget - total_spent, 2),
        by_category=by_category,
        top_expenses=top_expenses,
        day_of_month=day,
        days_in_month=total_days,
        over_budget=[c for c in by_category if c.budget > 0 and c.delta < 0],
        under_budget_remaining=[c for c in by_category if c.budget > 0 and c.delta > 0],
    )


def _latest_expense_month(conn) -> str | None:
    row = conn.execute("SELECT max(substr(date, 1, 7)) AS m FROM expense").fetchone()
    return row["m"] if row and row["m"] else None


def _span_where(span: Span | None) -> tuple[str, list]:
    """An inclusive date interval, which keeps this off `substr` and lets the
    index on `date` do the work. Filtering by date rather than by month is what
    makes a one-week horizon actually mean seven days."""
    if span is None:
        return "", []
    if span.start is None:
        return " AND date <= ?", [span.end]
    return " AND date >= ? AND date <= ?", [span.start, span.end]


def _spent_by_category(conn, span: Span | None) -> dict[str, float]:
    where, args = _span_where(span)
    sql = f"SELECT category, SUM(amount) AS total FROM expense WHERE 1=1{where} GROUP BY category"
    return {
        r["category"]: round(float(r["total"]), 2) for r in conn.execute(sql, args)
    }


def _budget_by_category(conn, months: list[str]) -> dict[str, float]:
    """Summed across every month in range — one query, not one per month."""
    if months:
        marks = ", ".join("?" for _ in months)
        sql = (
            f"SELECT category, SUM(amount) AS total FROM budget"
            f" WHERE month IN ({marks}) GROUP BY category"
        )
        args: list = list(months)
    else:
        sql = "SELECT category, SUM(amount) AS total FROM budget GROUP BY category"
        args = []
    return {r["category"]: round(float(r["total"]), 2) for r in conn.execute(sql, args)}


def _month_after(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return f"{y + 1:04d}-01-01" if m == 12 else f"{y:04d}-{m + 1:02d}-01"


def _calendar_progress(month: str, today: str | None) -> tuple[int, int]:
    """How far through the month we are, so budget burn can be read against
    it. 84% of budget spent on day 27 of 31 is fine; on day 12 it is not."""
    y, m = int(month[:4]), int(month[5:7])
    total_days = calendar.monthrange(y, m)[1]
    t = dt.date.fromisoformat(today) if today else dt.date.today()
    t_month = f"{t.year:04d}-{t.month:02d}"
    if t_month == month:
        return t.day, total_days
    return (total_days, total_days) if t_month > month else (0, total_days)


# ── the expenses pane's one query ────────────────────────────────────────
_SORT_COLUMN = {"date": "date", "amount": "amount", "category": "category"}


def _escape_like(text: str) -> str:
    """A description containing % or _ must match literally, not as a wildcard."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def query_expenses(conn, view) -> list[sqlite3.Row]:
    """Every combination of span, sort and the two filters, in one statement.

    Taking a MoneyView rather than eight keyword arguments is deliberate: the
    combinations are the thing that needs testing, and they are only testable as
    a unit if they arrive as one.
    """
    sql = "SELECT * FROM expense WHERE 1=1"
    where, args = _span_where(view.span())
    sql += where

    if view.filter_category:
        sql += " AND category = ?"
        args.append(view.filter_category)
    if view.filter_text:
        needle = f"%{_escape_like(view.filter_text.lower())}%"
        sql += (
            " AND (lower(description) LIKE ? ESCAPE '\\'"
            " OR lower(category) LIKE ? ESCAPE '\\')"
        )
        args.extend([needle, needle])

    column = _SORT_COLUMN.get(view.sort_field)
    if column is None:
        raise MoneyError(f"cannot sort by {view.sort_field!r}")
    direction = "DESC" if view.sort_desc else "ASC"
    sql += f" ORDER BY {column} {direction}, id {direction} LIMIT ?"
    args.append(_LIMIT_CAP)
    return list(conn.execute(sql, args))


def group_expenses(
    rows, *, collapsed: frozenset[str]
) -> list[tuple[str, float, int, list[sqlite3.Row]]]:
    """`(slug, total, count, rows)` ordered by total descending — a grouped view
    answers "where did most of it go". `rows` is empty for a collapsed group, but
    the total and count still show, so collapsing hides detail without hiding
    magnitude."""
    buckets: dict[str, list] = {}
    for r in rows:
        buckets.setdefault(r["category"], []).append(r)
    out = [
        (
            slug,
            round(sum(float(r["amount"]) for r in rs), 2),
            len(rs),
            [] if slug in collapsed else rs,
        )
        for slug, rs in buckets.items()
    ]
    out.sort(key=lambda g: g[1], reverse=True)
    return out
