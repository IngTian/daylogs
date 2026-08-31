"""Tab 3 — the daily summary: render, generate, browse.

Generation runs in a worker because `claude -p` takes seconds; everything else
in the app is microseconds and runs on the event loop.
"""

from __future__ import annotations

import datetime as dt

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Markdown, Static

from daybook import body, money, summary
from daybook import horizon as hz
from daybook.fmt import human_date
from daybook.markup import to_markdown
from daybook.tui.common import PanelTab

_EMPTY = "no summary yet — press r"


class SummaryTab(PanelTab):
    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.viewing_date: str | None = None
        self.busy = False

    def compose(self) -> ComposeResult:
        yield Static(id="day-head", classes="pane-title")
        with Horizontal(classes="panel-row"):
            with Vertical(classes="panel", id="panel-day-body"):
                yield Static("BODY", classes="panel-title")
                yield Static(id="day-body-body", classes="panel-body")
            with Vertical(classes="panel", id="panel-day-money"):
                yield Static("MONEY", classes="panel-title")
                yield Static(id="day-money-body", classes="panel-body")
        yield Static(id="summary-head", classes="pane-title")
        with VerticalScroll(id="summary-scroll"):
            # A real Markdown widget, so `## Body` renders as a heading instead of
            # showing the hashes. v1 fed markdown to a Static, which rendered the
            # source text verbatim.
            yield Markdown(id="summary-body")
        yield Static(id="summary-empty", classes="muted")

    def focus_default(self) -> None:
        return None

    def _body_panel(self, conn, cfg, *, date: str) -> str:
        """Today's body figures. Every value comes from body.py — this only lays out.

        Aligned in a value column like the Body tab's ENERGY panel, so the two read
        as the same app.
        """
        lines: list[str] = []
        latest = body.latest_weight(conn, on_or_before=date)
        if latest is None:
            # Name the key, not the file: an empty panel with no way out is how the
            # Body tab's energy block stayed blank.
            lines.append("  weight          —   press w on Body")
            kg = None
        else:
            kg = latest["kg"]
            d7 = body.weight_delta(conn, end_date=date, days=7)
            trend = "" if d7 is None else f"  {'▼' if d7 < 0 else '▲'}{abs(d7):g} vs 7d"
            lines.append(f"  weight    {kg:>7,.1f} kg{trend}")

        kcal = body.day_kcal(conn, date=date)
        bmr = body.compute_bmr(cfg, kg, today=date)
        if bmr is None:
            lines.append(f"  in        {kcal:>7,} kcal")
            lines.append("  BMR             —   press h on Body")
        else:
            lines.append(f"  in        {kcal:>7,} / {bmr:,} BMR")
            lines.append(f"  net       {kcal - bmr:>+7,} kcal")

        meals = len(body.list_food(conn, date=date))
        lines.append(f"  logged    {meals:>7} meal{'' if meals == 1 else 's'}")
        return "\n".join(lines)

    def _money_panel(self, conn, cfg, *, date: str) -> str:
        """This month's spend against its budget. One summarize_month call.

        The burn line only means something for a month in progress — 84% on day 27
        of 31 is fine and the same number on day 12 is not — so it is omitted for a
        past month rather than shown misleadingly.
        """
        month = date[:7]
        s = money.summarize_month(conn, month=month, today=date, cfg=cfg)
        lines: list[str] = [f"  spent   {s.total_spent:>10,.2f}"]

        pending, _ = money.pending_roll(conn, month=month)
        if s.total_budget <= 0:
            # Name the key. A zero budget is true and useless.
            lines.append(f"  budget          —   press r on Money ({pending} to roll)")
        else:
            lines[0] = f"  spent   {s.total_spent:>10,.2f} of {s.total_budget:,.2f}"
            lines.append(f"  left    {s.remaining:>10,.2f}")
            if month == self.app.today()[:7]:
                pct = round(s.total_spent / s.total_budget * 100)
                lines.append(f"  burn    {pct:>9}% on day {s.day_of_month}/{s.days_in_month}")

        if s.over_budget:
            names = ", ".join(c.category for c in s.over_budget[:2])
            lines.append(f"  over      {names}  ⚠")
        return "\n".join(lines)

    # ── rendering ────────────────────────────────────────────────────────
    def reload(self) -> None:
        conn = self.app.conn
        today = self.app.today()
        self.query_one("#day-head", Static).update(f"TODAY   {human_date(today)}")
        self.query_one("#day-body-body", Static).update(
            self._body_panel(self.app.conn, self.app.cfg, date=today)
        )
        self.query_one("#day-money-body", Static).update(
            self._money_panel(self.app.conn, self.app.cfg, date=today)
        )
        row = (
            summary.get_report(conn, self.viewing_date)
            if self.viewing_date
            else summary.latest_report(conn)
        )
        head = self.query_one("#summary-head", Static)
        body = self.query_one("#summary-body", Markdown)
        empty = self.query_one("#summary-empty", Static)

        if row is None:
            self.viewing_date = None
            head.update("SUMMARY" + ("   generating…" if self.busy else ""))
            body.update("")
            body.display = False
            empty.update("" if self.busy else _EMPTY)
            empty.display = not self.busy
            return

        self.viewing_date = row["date"]
        stamp = dt.datetime.fromtimestamp(row["generated_at"]).strftime("%H:%M")
        suffix = "   generating…" if self.busy else ""
        head.update(f"SUMMARY   {human_date(row['date'])}   generated {stamp}{suffix}")
        body.display = True
        empty.display = False
        body.update(to_markdown(row["content"]))

    def status_hint(self) -> str:
        if self.busy:
            return "generating…"
        return human_date(self.viewing_date) if self.viewing_date else "no summary"

    # ── keys ─────────────────────────────────────────────────────────────
    def key_generate(self) -> None:
        target = self.viewing_date or summary.target_date(self.app.today())
        self.generate(target)

    def key_prev_period(self) -> None:
        current = self.viewing_date or self.app.today()
        earlier = summary.prev_report_date(self.app.conn, current)
        if earlier is None:
            self.app.notify("no earlier summary", timeout=3)
            return
        self.viewing_date = earlier
        self.reload()

    def key_next_period(self) -> None:
        if self.viewing_date is None:
            return
        later = summary.next_report_date(self.app.conn, self.viewing_date)
        if later is None:
            self.app.notify("no later summary", timeout=3)
            return
        self.viewing_date = later
        self.reload()

    def key_jump_now(self) -> None:
        """Back to the newest report — the one you almost always want."""
        newest = summary.latest_report(self.app.conn)
        self.viewing_date = newest["date"] if newest else None
        self.reload()

    def key_back(self) -> bool:
        return False

    def handle_prompt(self, label: str, value: str) -> None:
        if label == "go to date" and value:
            wanted = hz.resolve_goto(value)
            if summary.get_report(self.app.conn, wanted) is None:
                self.app.notify(f"no summary for {wanted}", timeout=4)
                return
            self.viewing_date = wanted
            self.reload()

    # ── worker ───────────────────────────────────────────────────────────
    @work(exclusive=True)
    async def generate(self, date: str) -> None:
        self.busy = True
        self.reload()
        try:
            await summary.generate(
                self.app.conn,
                self.app.cfg,
                date=date,
                runner=self.app.runner_text,
            )
        except Exception as e:  # noqa: BLE001 - surfaced to the user, not swallowed
            self.busy = False
            self.reload()
            self.app.notify_error(f"summary failed: {e}")
            return
        self.busy = False
        self.viewing_date = date
        self.reload()


