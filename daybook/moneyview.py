"""The Money tab's whole view state, as one value.

Sorting, grouping, filtering, drill-down and the time horizon all act on the same
pane. As separate flags they would produce a combinatorial pile of half-tested
states; as one object with named transitions, each has a method and a test.

The horizon comes from `horizon.py`, shared with the Body chart, so `+`/`-` means
the same thing on both tabs.

Pure: no Textual, no database.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from daybook import horizon as hz

SORT_FIELDS = ("date", "amount", "category")
PANES = ("categories", "expenses", "recurring")

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ViewError(ValueError):
    pass


@dataclass
class MoneyView:
    anchor: str                       # a DATE: the right-hand edge of the span
    horizon: str = hz.DEFAULT
    pane: str = "categories"
    sort_field: str = "date"
    sort_desc: bool = True
    filter_text: str = ""
    filter_category: str | None = None
    grouped: bool = False
    collapsed: frozenset[str] = field(default_factory=frozenset)

    # ── span ─────────────────────────────────────────────────────────────
    def span(self) -> hz.Span:
        return hz.resolve(self.horizon, anchor=self.anchor)

    def months(self) -> list[str]:
        """Calendar months the span touches — budgets are stored per month."""
        return self.span().months()

    def label(self) -> str:
        return self.span().label

    def is_single_current_month(self, today: str) -> bool:
        """Burn-against-elapsed only means something for month-to-date on the
        month actually running. Drawing the calendar marker for a rolling week or
        a past month would invite a false read."""
        return self.horizon == "MTD" and self.anchor[:7] == today[:7]

    def step(self, delta: int) -> None:
        self.anchor = hz.shift(self.horizon, self.anchor, delta)

    def widen(self) -> None:
        self.horizon = hz.next_horizon(self.horizon, 1)

    def narrow(self) -> None:
        self.horizon = hz.next_horizon(self.horizon, -1)

    # ── sort ─────────────────────────────────────────────────────────────
    def set_sort(self, field_name: str) -> None:
        """Same field flips direction; a different field switches and resets to
        descending. The common idiom, and the one that needs no explaining."""
        if field_name not in SORT_FIELDS:
            raise ViewError(f"sort field must be one of {SORT_FIELDS}")
        if self.sort_field == field_name:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_field = field_name
            self.sort_desc = True

    # ── jumping ──────────────────────────────────────────────────────────
    def jump_to(self, today: str) -> None:
        self.anchor = today
        self.filter_text = ""
        self.filter_category = None

    def goto(self, text: str) -> None:
        """Delegates to `horizon.resolve_goto` — the rule lives there because three
        tabs need it and two hand-cloned copies had already drifted."""
        try:
            self.anchor = hz.resolve_goto(text)
        except hz.HorizonError as e:
            raise ViewError(str(e)) from e

    @staticmethod
    def _check(iso: str) -> None:
        try:
            dt.date.fromisoformat(iso)
        except ValueError as e:
            raise ViewError(f"{iso} is not a real date") from e

    # ── the escape stack ─────────────────────────────────────────────────
    def back(self) -> bool:
        """Unwind exactly one narrowing, returning whether anything happened.

        Grouped mode is deliberately not on this list: it is a view preference,
        not a narrowing. Mixing preferences into an undo stack is how "back"
        becomes unpredictable.
        """
        if self.filter_text:
            self.filter_text = ""
            return True
        if self.filter_category is not None:
            self.filter_category = None
            self.pane = "categories"
            return True
        return False

    # ── grouping ─────────────────────────────────────────────────────────
    def toggle_collapsed(self, slug: str) -> None:
        self.collapsed = (
            self.collapsed - {slug} if slug in self.collapsed else self.collapsed | {slug}
        )
