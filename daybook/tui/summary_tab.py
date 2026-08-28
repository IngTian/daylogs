"""Tab 3 — the daily summary: render, generate, browse.

Generation runs in a worker because `claude -p` takes seconds; everything else
in the app is microseconds and runs on the event loop.
"""

from __future__ import annotations

import datetime as dt

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Markdown, Static

from daybook import horizon as hz
from daybook import summary
from daybook.fmt import human_date
from daybook.markup import to_markdown

_EMPTY = "no summary yet — press r"


class SummaryTab(Vertical):
    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.viewing_date: str | None = None
        self.busy = False

    def compose(self) -> ComposeResult:
        yield Static(id="summary-head", classes="pane-title")
        with VerticalScroll(id="summary-scroll"):
            # A real Markdown widget, so `## Body` renders as a heading instead of
            # showing the hashes. v1 fed markdown to a Static, which rendered the
            # source text verbatim.
            yield Markdown(id="summary-body")
        yield Static(id="summary-empty", classes="muted")

    def focus_default(self) -> None:
        return None

    # ── rendering ────────────────────────────────────────────────────────
    def reload(self) -> None:
        conn = self.app.conn
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


