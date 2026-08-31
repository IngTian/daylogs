"""Tab 3 — expenses, budgets and recurring items over any range.

Expenses only: no income, no balance, no projection. Every number comes from
money.summarize_span and money.query_expenses; all view state lives in one
MoneyView. This file decides layout and keys.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Static

from daybook import money, parse
from daybook.moneyview import PANES, MoneyView
from daybook.parse import parse_budget, parse_expense, parse_recurring
from daybook.tui.common import PanelTab
from daybook.tui.widgets import (
    BAD,
    FAINT,
    GOOD,
    WARN,
    budget_bars,
    burn_bar,
    esc,
    mark,
    ranked_bars,
    signed,
    wide_sparkline,
)
from daybook.tui.widgets import money as fmt

_ARROW = {True: "↓", False: "↑"}
_SORT_LABEL = {"date": "date", "amount": "cost", "category": "category"}

# How close to a cap counts as "watch it" rather than "fine". 90% on the 28th is
# not the same news as 90% on the 5th, but the burn marker carries the calendar —
# this is only about the per-category bar.
_WARN_FRAC = 0.9

# Six cells of block glyphs read as noise at a terminal font size; each month
# needs several cells before the shape is legible.
_SPARK_W = 24


def _budget_style(spent: float, budget: float) -> str:
    """Over the cap is bad, near it is a warning, a refund is neither."""
    if budget <= 0 or spent < 0:
        return ""
    if spent > budget:
        return BAD
    return WARN if spent / budget >= _WARN_FRAC else GOOD


class MoneyTab(PanelTab):
    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        # A full date: the anchor is the right-hand edge of the span, replaced with
        # today in on_mount. A month string would fail date parsing.
        self.view = MoneyView(anchor="1970-01-01")
        self._ids: list[int] = []
        self._groups: list[str] = []
        # The row an open edit prompt belongs to; InlinePrompt carries no id.
        self._editing: tuple[str, int] | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="money-head", classes="pane-title")
        yield Static(id="money-bar", classes="chart")
        # Two panels side by side: each category against its own cap, and the
        # part-to-whole ranking. v2 left this space empty.
        with Horizontal(classes="panel-row"):
            with Vertical(classes="panel", id="panel-budget"):
                yield Static("BUDGET vs SPENT", classes="panel-title")
                yield Static(id="budget-body", classes="panel-body")
            with Vertical(classes="panel", id="panel-share"):
                yield Static("WHERE IT WENT", classes="panel-title")
                yield Static(id="share-body", classes="panel-body")
        yield Static(id="money-panes", classes="muted")
        yield DataTable(id="money-table", cursor_type="row")

    def on_mount(self) -> None:
        self.view.anchor = self.app.today()

    def focus_default(self) -> None:
        self.query_one("#money-table", DataTable).focus()

    def cancel_editing(self) -> None:
        """Drop the armed edit id when a prompt is cancelled."""
        self._editing = None

    def status_hint(self) -> str:
        """The footer's state row: range, active filters, and the sort.

        The sort shows all three fields with the active one marked, rather than
        only naming the current one: seeing the options beside the choice tells you
        what else is available without pressing `?`.
        """
        v = self.view
        parts = [mark(v.label().lower(), "bold")]
        if v.filter_category:
            parts.append(f"in {v.filter_category}")
        if v.filter_text:
            # User input into a markup string: filtering on "[" would otherwise
            # open a tag and eat the rest of the row.
            parts.append(f'"{esc(v.filter_text)}"')
        if v.grouped:
            parts.append("grouped")
        chips = " · ".join(parts)
        fields = " ".join(
            mark(f"{_ARROW[v.sort_desc]}{label}", "bold")
            if field == v.sort_field
            else mark(label, FAINT)
            for field, label in _SORT_LABEL.items()
        )
        return f"{chips}    {mark('sort', FAINT)} {fields}"

    # ── rendering ────────────────────────────────────────────────────────
    def reload(self) -> None:
        v = self.view
        span = v.span()
        months = span.months()
        s = money.summarize_span(
            self.app.conn, span=span, today=self.app.today(), cfg=self.app.cfg
        )

        bar_widget = self.query_one("#money-bar", Static)
        if s.total_budget <= 0:
            # No budget rows in this span at all. "0.00 budget / 1,234.00 over"
            # with an empty burn bar is true and useless — it reads as stale data
            # when the real state is "nobody rolled this month yet". Name the fix
            # instead, and drop the bar rather than draw a 0% one.
            head = f"{v.label()}   spent {fmt(s.total_spent)}   ·  {self._no_budget_hint(months)}"
            # Clear as well as hide. Hiding alone left the previous month's bar in
            # the widget — invisible, but stale, and wrong the moment it is shown
            # again. A test stepping back to a budget-less month caught this.
            bar_widget.update("")
            bar_widget.display = False
        else:
            over = s.remaining < 0
            remaining = mark(
                f"{fmt(abs(s.remaining))} {'over' if over else 'left'}",
                f"bold {BAD}" if over else GOOD,
            )
            head = (
                f"{v.label()}   spent {fmt(s.total_spent)}"
                f" / {fmt(s.total_budget)} budget   {remaining}"
            )
            pct = round(s.total_spent / s.total_budget * 100)
            single = v.is_single_current_month(self.app.today())
            if single and s.days_in_month:
                frac = s.day_of_month / s.days_in_month
                tail = f"{pct}% · day {s.day_of_month} of {s.days_in_month}"
            else:
                # Burn-against-elapsed is meaningless across a quarter, so the
                # marker is withheld rather than drawn somewhere arbitrary.
                frac = None
                n = len(months) or "all"
                tail = f"{pct}% · budget summed over {n} months"
            bar = burn_bar(s.total_spent, s.total_budget, width=40, marker_frac=frac)
            # Colour the burn, not the tail: the bar is the thing read at a glance.
            bar_widget.display = True
            bar_widget.update(f"{mark(bar, BAD if over else GOOD)}  {tail}")
        self.query_one("#money-head", Static).update(head)

        self._fill_panels(s)
        self.query_one("#money-panes", Static).update(
            "   ".join(f"[b]{p}[/b]" if p == v.pane else p for p in PANES)
        )
        self._fill_table(s)

    def _no_budget_hint(self, months: list[str]) -> str:
        """Why there is no budget, and the one key that fixes it.

        Only the current month can be rolled, so a multi-month span says what it
        is rather than offering a key that would only half-apply.
        """
        if len(months) != 1:
            return mark("no budget set for this range", WARN)
        count, total = money.pending_roll(self.app.conn, month=months[0])
        if not count:
            return mark("no budget set — press b to add a line", WARN)
        return mark(f"no budget yet — r rolls {count} recurring → {fmt(total)}", WARN)

    def _fill_panels(self, s) -> None:
        # `!= 0`, not `> 0`: a category that nets negative over the window — a
        # reimbursed bill, a returned order — is real and belongs on both panels.
        # Filtering it out left WHERE IT WENT adding up to gross spend while the
        # header showed the net, with nothing on screen to explain the gap. The
        # renderers give such a row its amount and no share.
        spent = [c for c in s.by_category if c.spent != 0]
        budgeted = sorted(
            (c for c in s.by_category if c.budget > 0 or c.spent != 0),
            key=lambda c: c.budget,
            reverse=True,
        )
        budget_lines = budget_bars(
            [(c.category, c.spent, c.budget) for c in budgeted],
            width=self.panel_width("#panel-budget", minimum=28)
        )
        # Colour whole finished lines, never the pieces: the builders truncate on
        # character count, and markup would be counted as content.
        budget_lines = [
            mark(line, _budget_style(c.spent, c.budget))
            for line, c in zip(budget_lines, budgeted, strict=True)
        ]
        self.query_one("#budget-body", Static).update(
            "\n".join(budget_lines) if budget_lines else "  no budget lines yet — press b"
        )

        ranked = sorted(spent, key=lambda c: c.spent, reverse=True)
        share_lines = ranked_bars(
            [(c.category, c.spent) for c in ranked],
            width=self.panel_width("#panel-share", minimum=28)
        )
        self.query_one("#share-body", Static).update(
            "\n".join(share_lines) if share_lines else "  nothing spent in this window"
        )

    def _fill_table(self, s) -> None:
        table = self.query_one("#money-table", DataTable)
        table.clear(columns=True)
        self._ids = []
        self._groups = []
        if self.view.pane == "categories":
            self._fill_categories(table, s)
        elif self.view.pane == "expenses":
            self._fill_expenses(table)
        else:
            self._fill_recurring(table)

    def _fill_categories(self, table, s) -> None:
        table.add_columns("category", "budget", "spent", "Δ", f"6-mo{'':>{_SPARK_W - 4}}")
        over = {c.category for c in s.over_budget}
        for c in s.by_category:
            flag = "  ⚠" if c.category in over else ""
            # Text, not markup, for cells: DataTable measures column widths from
            # the cell's own render, so a "[red]…[/]" string would both print
            # literally and widen the column by nine characters.
            delta = Text(signed(c.delta), style=GOOD if c.delta >= 0 else BAD)
            table.add_row(
                c.category + flag,
                fmt(c.budget),
                fmt(c.spent),
                delta,
                Text(wide_sparkline(c.history, width=_SPARK_W, from_zero=True), style=FAINT),
            )
            self._ids.append(-1)
            self._groups.append(c.category)

    def _fill_expenses(self, table) -> None:
        rows = money.query_expenses(self.app.conn, self.view)
        if not self.view.grouped:
            table.add_columns("date", "description", "category", "amount")
            for r in rows:
                table.add_row(r["date"], r["description"], r["category"], fmt(r["amount"]))
                self._ids.append(r["id"])
                self._groups.append("")
            return

        table.add_columns("", "date / category", "description", "amount")
        for slug, total, count, children in money.group_expenses(
            rows, collapsed=self.view.collapsed
        ):
            marker = "▸" if slug in self.view.collapsed else "▾"
            table.add_row(marker, slug, f"{count} rows", fmt(total))
            self._ids.append(-1)
            self._groups.append(slug)
            for r in children:
                table.add_row("", f"  {r['date']}", r["description"], fmt(r["amount"]))
                self._ids.append(r["id"])
                self._groups.append("")

    def _fill_recurring(self, table) -> None:
        table.add_columns("name", "category", "cost", "cycle", "monthly", "on")
        for r in money.list_recurring(self.app.conn):
            table.add_row(
                r["name"],
                r["category"],
                fmt(r["cost"]),
                r["cycle"],
                fmt(r["monthly_cost"]),
                "yes" if r["active"] else "no",
            )
            self._ids.append(r["id"])
            self._groups.append("")

    def _cursor(self) -> int | None:
        table = self.query_one("#money-table", DataTable)
        row = table.cursor_row
        if row is None or not (0 <= row < len(self._ids)):
            return None
        return row

    def _selected_id(self) -> int | None:
        i = self._cursor()
        if i is None:
            return None
        return None if self._ids[i] < 0 else self._ids[i]

    def _selected_group(self) -> str:
        i = self._cursor()
        return self._groups[i] if i is not None else ""

    # ── keys ─────────────────────────────────────────────────────────────
    def key_expense(self) -> None:
        self.app.prompt.open("expense")

    def key_budget(self) -> None:
        self.app.prompt.open("budget")

    def key_recurring(self) -> None:
        self.app.prompt.open("recurring")

    def key_filter(self) -> None:
        self.app.prompt.open("filter", self.view.filter_text)

    def key_next_subview(self) -> None:
        self.view.pane = PANES[(PANES.index(self.view.pane) + 1) % len(PANES)]
        self.reload()

    def key_prev_subview(self) -> None:
        self.view.pane = PANES[(PANES.index(self.view.pane) - 1) % len(PANES)]
        self.reload()

    def key_prev_period(self) -> None:
        self.view.step(-1)
        self.reload()

    def key_next_period(self) -> None:
        self.view.step(1)
        self.reload()

    def key_jump_now(self) -> None:
        self.view.jump_to(self.app.today())
        self.reload()

    def key_zoom_in(self) -> None:
        self.view.widen()
        self.reload()

    def key_zoom_out(self) -> None:
        self.view.narrow()
        self.reload()

    def key_sort_date(self) -> None:
        self._sort("date")

    def key_sort_cost(self) -> None:
        self._sort("amount")

    def key_sort_category(self) -> None:
        self._sort("category")

    def _sort(self, field_name: str) -> None:
        self.view.set_sort(field_name)
        if self.view.pane == "categories":
            self.view.pane = "expenses"  # sorting is about rows, so show them
        self.reload()

    def key_toggle_group(self) -> None:
        self.view.grouped = not self.view.grouped
        if self.view.grouped and self.view.pane != "expenses":
            self.view.pane = "expenses"
        self.reload()

    def key_activate(self) -> None:
        """enter acts on whatever is under the cursor.

        One mental model, three outcomes by row kind: a category drills in, a group
        header folds, an actual row opens for editing. The first two already
        behaved this way; the third used to fall through and do nothing.
        """
        if self.view.pane == "categories":
            slug = self._selected_group()
            if slug:
                self.view.filter_category = slug
                self.view.pane = "expenses"
                self.reload()
            return
        # A group header has no id, so this ordering matters: fold first, and only
        # treat the row as editable when it is a real row.
        if self.view.grouped and self._selected_group():
            self.view.toggle_collapsed(self._selected_group())
            self.reload()
            return
        row_id = self._selected_id()
        if row_id is None:
            return
        which = "expense" if self.view.pane == "expenses" else "recurring"
        row = self.app.conn.execute(
            f"SELECT * FROM {which} WHERE id = ?", (row_id,)
        ).fetchone()
        if row is None:
            return
        self._editing = (which, row_id)
        if which == "expense":
            self.app.prompt.open("expense", prefill=parse.render_expense(row))
        else:
            self.app.prompt.open("recurring", prefill=parse.render_recurring(row))

    def key_back(self) -> bool:
        return self.view.back()

    def key_roll(self) -> None:
        month = self.view.months()[-1] if self.view.months() else self.app.today()[:7]
        n = money.roll_month_budgets(self.app.conn, month=month, cfg=self.app.cfg)
        self.app.notify(
            f"{n} recurring line{'s' if n != 1 else ''} rolled into {month}", timeout=4
        )
        self.reload()

    def key_delete(self) -> None:
        if self.view.pane == "categories":
            self.app.notify("switch to expenses or recurring to delete (tab)", timeout=4)
            return
        row_id = self._selected_id()
        if row_id is None:
            self.app.notify("select a row, not a group header", timeout=3)
            return
        pane = self.view.pane
        which = "expense" if pane == "expenses" else "recurring"
        row = self.app.conn.execute(
            f"SELECT * FROM {which} WHERE id = ?", (row_id,)
        ).fetchone()
        if row is None:
            return
        if which == "expense":
            label = f"{row['date']}  {row['description']}  {fmt(row['amount'])}"
        else:
            label = f"{row['name']}  {fmt(row['monthly_cost'])}/mo"
        self.app.ask_confirm(
            f"delete {label}?   y/n", lambda: self._do_delete(pane, row_id)
        )

    def _do_delete(self, pane: str, row_id: int) -> None:
        table = "expense" if pane == "expenses" else "recurring"
        fn = money.delete_expense if pane == "expenses" else money.delete_recurring
        row = fn(self.app.conn, row_id)
        if row is None:
            return
        self.app.undo_stack.push(table, row)
        self.app.notify("deleted · u to undo", timeout=4)
        self.reload()

    # ── prompt handling ──────────────────────────────────────────────────
    def handle_prompt(self, label: str, value: str) -> None:
        """Malformed input raises; the app keeps the text and shows why."""
        if not value:
            return
        if label == "expense":
            self._submit_expense(value)
        elif label == "fix category":
            self._submit_expense(value, refiling=True)
        elif label == "budget":
            self._submit_budget(value)
        elif label == "recurring":
            self._submit_recurring(value)
        elif label == "filter":
            self.view.filter_text = value
            self.view.pane = "expenses"
            self.reload()
        elif label == "go to date":
            self.view.goto(value)
            self.reload()

    def _submit_expense(self, value: str, *, refiling: bool = False) -> None:
        cfg = self.app.cfg
        r = parse_expense(value, now=self.app.now(), known_slugs=money.slugs(cfg))
        row_id = self._take_editing("expense")
        if row_id is None:
            money.add_expense(
                self.app.conn,
                amount=r.amount,
                description=r.description,
                category=r.category,
                date=r.date,
                note=r.note,
                cfg=cfg,
            )
            # The anchor is a date, not a month: move the span's right edge to the day
            # just logged so the new row is inside whatever horizon is active.
            self.view.anchor = max(self.view.anchor, r.date)
            self.reload()

            s = money.summarize_span(
                self.app.conn, span=self.view.span(), today=self.app.today(), cfg=cfg
            )
            cat = next((c for c in s.by_category if c.category == r.category), None)
            # Always name the category: confirming *where it was filed* is the most
            # useful part, and it is the thing most likely to be wrong.
            if cat is None or cat.budget <= 0:
                spent = cat.spent if cat else abs(r.amount)
                tail = f"{r.category} {fmt(spent)} this range · no budget"
            else:
                over = " ⚠" if cat.delta < 0 else ""
                tail = f"{r.category} {fmt(cat.spent)} of {fmt(cat.budget)}{over}"
            self.app.notify(f"{fmt(r.amount)} {r.description} → {tail}", timeout=5)

            if r.category == "other" and not refiling:
                # Written, but flagged: an uncategorised row is more likely a typo
                # than an intent. Re-open prefilled so the fix is one edit, not a hunt
                # through the table later.
                self.app.prompt.open("fix category", value)
            return
        before = self.app.conn.execute(
            "SELECT * FROM expense WHERE id = ?", (row_id,)
        ).fetchone()
        if before is None:
            self.app.notify("that row is gone", timeout=3)
            return
        # Push the pre-image only once the write has succeeded: a MoneyError would
        # otherwise leave a bogus entry that `u` applies to a row which never changed.
        money.update_expense(
            self.app.conn, row_id, cfg,
            amount=r.amount, description=r.description, category=r.category,
            date=r.date, note=r.note or ""
        )
        self.app.undo_stack.push("expense", dict(before))
        self.app.notify(f"{fmt(r.amount)} {r.description} → {r.category} · u to undo", timeout=4)
        self.reload()

    def _submit_budget(self, value: str) -> None:
        cfg = self.app.cfg
        r = parse_budget(value, now=self.app.now(), known_slugs=money.slugs(cfg))
        month = self.view.months()[-1] if self.view.months() else self.app.today()[:7]
        money.upsert_budget(
            self.app.conn,
            month=month,
            name=r.name,
            category=r.category,
            amount=r.amount,
            cfg=cfg,
        )
        self.reload()
        s = money.summarize_span(
            self.app.conn, span=self.view.span(), today=self.app.today(), cfg=cfg
        )
        cat = next((c for c in s.by_category if c.category == r.category), None)
        spent = cat.spent if cat else 0.0
        left = (cat.delta if cat else r.amount)
        self.app.notify(
            f"budget {r.category} {fmt(r.amount)} · {fmt(spent)} spent,"
            f" {fmt(left)} left",
            timeout=5,
        )

    def _take_editing(self, which: str) -> int | None:
        """The id an open edit prompt belongs to, consumed once.

        Cleared on read so a stale id cannot be reused by the next submission — the
        row may have been deleted in between.
        """
        if self._editing is None or self._editing[0] != which:
            return None
        _, row_id = self._editing
        self._editing = None
        return row_id

    def _submit_recurring(self, value: str) -> None:
        cfg = self.app.cfg
        r = parse_recurring(value, now=self.app.now(), known_slugs=money.slugs(cfg))
        row_id = self._take_editing("recurring")
        if row_id is None:
            money.upsert_recurring(
                self.app.conn,
                name=r.name,
                cost=r.cost,
                cycle=r.cycle,
                category=r.category,
                cfg=cfg,
            )
            self.view.pane = "recurring"
            self.reload()
            monthly = money.monthly_equivalent(r.cost, r.cycle)
            self.app.notify(
                f"{r.name} · {fmt(r.cost)} {r.cycle} = {fmt(monthly)}/mo · r to roll",
                timeout=5,
            )
            return
        before = self.app.conn.execute(
            "SELECT * FROM recurring WHERE id = ?", (row_id,)
        ).fetchone()
        if before is None:
            self.app.notify("that row is gone", timeout=3)
            return
        # update_recurring is keyed by id, not name (upsert_recurring resolves on
        # name, so a rename through upsert would INSERT a second row).
        money.update_recurring(
            self.app.conn, row_id, cfg,
            name=r.name, cost=r.cost, cycle=r.cycle, category=r.category
        )
        self.app.undo_stack.push("recurring", dict(before))
        monthly = money.monthly_equivalent(r.cost, r.cycle)
        self.app.notify(f"{r.name} · {fmt(monthly)}/mo · u to undo", timeout=4)
        self.reload()
