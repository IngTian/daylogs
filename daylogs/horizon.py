"""Time horizons, shared by the Body chart and the Money tab.

v2 had two unrelated concepts — chart windows (30d/90d/6mo/1y/all) on Body and
ranges (month/quarter/year/all) on Money — so `+` meant different things on
different tabs and neither offered month-to-date or year-to-date. One list now
serves both, which is both what was asked for and less to remember.

A horizon plus an anchor date resolves to a `Span`. Rolling horizons (1d, 1w, 1m,
3m, 1y) look back from the anchor; `MTD` and `YTD` run from the start of the
anchor's month or year. Pure: no database, no Textual.

`1d` is the narrow end, and it is what makes `Axis.fraction_at` worth having: on a
one-day axis the time of day *is* the horizontal position, so two readings hours
apart separate instead of stacking on one column.
"""

from __future__ import annotations

import calendar
import datetime as dt
import re
from dataclasses import dataclass

HORIZONS = ("1d", "3d", "1w", "1m", "MTD", "3m", "YTD", "1y", "all")

# Rolling look-back in days, for the horizons that are a fixed window.
_LOOKBACK = {"1d": 1, "3d": 3, "1w": 7, "1m": 30, "3m": 90, "1y": 365}
# How far one `[` / `]` press moves the anchor, in (months, days).
_STEP = {
    "1d": (0, 1),
    "3d": (0, 3),
    "1w": (0, 7),
    "1m": (1, 0),
    "MTD": (1, 0),
    "3m": (3, 0),
    "YTD": (12, 0),
    "1y": (12, 0),
    "all": (0, 0),
}

_DAY_SECONDS = 24 * 3600

# At or below this many days, a span is plotted and labelled by the hour: points
# sit at their real time of day and the axis ticks are clock times. Above it, a day
# is a column or two wide and sub-day precision is invisible, so the chart stays a
# daily trend. Shared so the tab's query and the axis agree on where the line is.
HOURLY_MAX_DAYS = 3

DEFAULT = "MTD"


class HorizonError(ValueError):
    pass


@dataclass(frozen=True)
class Span:
    """An inclusive date range. `start is None` means unbounded (all time)."""

    horizon: str
    start: str | None
    end: str

    @property
    def label(self) -> str:
        if self.start is None:
            return "ALL TIME"
        s, e = dt.date.fromisoformat(self.start), dt.date.fromisoformat(self.end)
        if self.horizon == "MTD":
            return f"{s.strftime('%B %Y').upper()} · to the {_ordinal(e.day)}"
        if self.horizon == "YTD":
            return f"{s.year} YTD · to {e.strftime('%b %-d')}"
        # A one-day span through the range branch renders as "Aug 28 – Aug 28 2026",
        # which reads as a formatting bug rather than as a day. Checked on the dates
        # rather than on `horizon == "1d"`, so any span that happens to cover one
        # day says so.
        if s == e:
            return f"{s.strftime('%a %b %-d %Y')}"
        if s.year == e.year:
            return f"{s.strftime('%b %-d')} – {e.strftime('%b %-d')} {e.year}"
        return f"{s.strftime('%b %-d %Y')} – {e.strftime('%b %-d %Y')}"

    @property
    def days(self) -> int | None:
        """Inclusive day count, or None when unbounded."""
        if self.start is None:
            return None
        s, e = dt.date.fromisoformat(self.start), dt.date.fromisoformat(self.end)
        return (e - s).days + 1

    @property
    def hourly(self) -> bool:
        """Short enough that the time of day is worth plotting.

        The tab asks this to decide whether to fetch every reading or one per day:
        a three-day window wants each weigh-in where it happened, a three-month one
        wants a clean daily trend.
        """
        return self.days is not None and self.days <= HOURLY_MAX_DAYS

    def months(self) -> list[str]:
        """Calendar months the span touches, ascending. Empty means unbounded.

        Budgets are stored per month, so a span's budget is the sum over these.
        """
        if self.start is None:
            return []
        s, e = dt.date.fromisoformat(self.start), dt.date.fromisoformat(self.end)
        out: list[str] = []
        y, m = s.year, s.month
        while (y, m) <= (e.year, e.month):
            out.append(f"{y:04d}-{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return out


_GOTO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_GOTO_MONTH = re.compile(r"^\d{4}-\d{2}$")


def resolve_goto(text: str) -> str:
    """The one place `g` turns typed text into a date.

    A full date lands on itself. A bare month lands on its **last** day, so
    `g 2026-06` under a month-to-date horizon gives you the whole of June rather
    than the first of it.

    This exists because the rule was implemented three times — once here in
    effect, and cloned into two tabs that each re-derived the date themselves and
    appended `-01`. When the month branch changed to return the last day, both
    clones started producing `2026-06-30-01`, which poisoned the tab's date and
    crashed the app on the next keypress. One rule, one function, three callers.
    """
    s = text.strip()
    if _GOTO_DATE.match(s):
        return _checked(s)
    if _GOTO_MONTH.match(s):
        _checked(f"{s}-01")
        y, m = int(s[:4]), int(s[5:7])
        return f"{s}-{calendar.monthrange(y, m)[1]:02d}"
    raise HorizonError("give a date like 2026-06-15 or a month like 2026-06")


def _checked(iso: str) -> str:
    try:
        dt.date.fromisoformat(iso)
    except ValueError as e:
        raise HorizonError(f"{iso} is not a real date") from e
    return iso


@dataclass(frozen=True)
class Axis:
    """The resolved horizontal extent of a plot: two real dates.

    A chart that spaces points evenly by index lies about time. Two weigh-ins a
    day apart, plotted across a month-wide panel, drew a smooth month-long climb;
    the same two points at their true positions sit together at the right edge
    with the unweighed weeks visibly empty. Gaps in the data are information.
    """

    left: str
    right: str

    def fraction(self, date: str) -> float:
        """`date`'s position in [0, 1] across the axis."""
        left = dt.date.fromisoformat(self.left)
        total = (dt.date.fromisoformat(self.right) - left).days
        if total <= 0:
            return 0.0
        offset = (dt.date.fromisoformat(date) - left).days
        return min(max(offset / total, 0.0), 1.0)

    def fractions(self, dates: list[str]) -> list[float]:
        return [self.fraction(d) for d in dates]

    def fraction_at(self, when: dt.datetime) -> float:
        """`when`'s position in [0, 1], to the hour rather than to the day.

        A bare date means midnight, so `fraction_at` at midnight equals `fraction`
        of the same date — every long horizon plots exactly where it did before, and
        the extra precision only becomes visible once a day is more than a column or
        two wide.

        Reads `when`'s own components and never converts a timezone: this module is
        pure, and the caller already knows which zone the clock is in. Hand it a
        local datetime.
        """
        into_day = when.hour * 3600 + when.minute * 60 + when.second
        left = dt.date.fromisoformat(self.left)
        total_days = (dt.date.fromisoformat(self.right) - left).days
        offset = (when.date() - left).days + into_day / _DAY_SECONDS
        if self.hourly:
            # Divide by the *inclusive* width, so the axis runs from the first day's
            # 00:00 to the last day's 24:00. With the exclusive divisor used below,
            # everything after midday on the final day would clamp to the right edge
            # — which is what you want when the newest reading means "now" on a
            # months-wide chart, and wrong when the point of the view is the clock.
            return min(max(offset / (total_days + 1), 0.0), 1.0)
        if total_days <= 0:
            return 0.0
        return min(max(offset / total_days, 0.0), 1.0)

    @property
    def hourly(self) -> bool:
        """Whether this axis is narrow enough to be read as a clock."""
        left = dt.date.fromisoformat(self.left)
        return (dt.date.fromisoformat(self.right) - left).days + 1 <= HOURLY_MAX_DAYS

    def fractions_at(self, moments: list[dt.datetime]) -> list[float]:
        return [self.fraction_at(m) for m in moments]

    def labels(self) -> tuple[str, ...]:
        """Up to three ticks describing the axis, not the data.

        Deriving these from the plotted points printed "Aug 27 / Aug 28 / Aug 28"
        for a month-long window — duplicated, and describing the wrong extent.
        """
        left = dt.date.fromisoformat(self.left)
        right = dt.date.fromisoformat(self.right)
        if left == right:
            # One day wide, so an hour scale says more than the same date three
            # times — and the tab header already carries the date.
            return ("00:00", "12:00", "24:00")
        if self.hourly:
            # Two or three days: the clock still matters, but hours alone would not
            # say which day. Weekday rather than date keeps each tick to nine
            # characters — three dates plus times would collide on a half-width
            # panel — and the header carries the dates.
            midnight = dt.datetime.combine(left, dt.time())
            mid = midnight + dt.timedelta(days=(right - left).days + 1) / 2
            return (
                f"{left.strftime('%a')} 00:00",
                mid.strftime("%a %H:%M"),
                f"{right.strftime('%a')} 24:00",
            )
        mid = left + (right - left) / 2
        return tuple(d.strftime("%b %d") for d in (left, mid, right))


def axis(span: Span, dates: list[str]) -> Axis:
    """The axis a span should be plotted on.

    An unbounded span ("all time") has no left edge of its own, so it borrows the
    earliest date actually present. Everything else uses the span, which is why an
    empty stretch at the start of a window still reads as empty.
    """
    left = span.start or (min(dates) if dates else span.end)
    return Axis(min(left, span.end), span.end)


def resolve(horizon: str, *, anchor: str) -> Span:
    if horizon not in HORIZONS:
        raise HorizonError(f"horizon must be one of {HORIZONS}")
    end = dt.date.fromisoformat(anchor)
    if horizon == "all":
        return Span(horizon, None, end.isoformat())
    if horizon == "MTD":
        start = end.replace(day=1)
    elif horizon == "YTD":
        start = end.replace(month=1, day=1)
    else:
        start = end - dt.timedelta(days=_LOOKBACK[horizon] - 1)
    return Span(horizon, start.isoformat(), end.isoformat())


def next_horizon(horizon: str, step: int) -> str:
    """Move along HORIZONS, clamping at both ends — wrapping from `all` back to
    `1w` on a keypress reads as a glitch."""
    try:
        i = HORIZONS.index(horizon)
    except ValueError:
        return DEFAULT
    return HORIZONS[min(max(i + step, 0), len(HORIZONS) - 1)]


def shift(horizon: str, anchor: str, delta: int) -> str:
    """Move the anchor by one whole horizon.

    MTD steps by a calendar month, so `[` compares the same elapsed slice of the
    previous month rather than a ragged window — which is the comparison that
    matters for budget burn.
    """
    if horizon not in HORIZONS:
        raise HorizonError(f"horizon must be one of {HORIZONS}")
    months, days = _STEP[horizon]
    d = dt.date.fromisoformat(anchor)
    if days:
        return (d + dt.timedelta(days=days * delta)).isoformat()
    if not months:
        return anchor
    total = d.year * 12 + (d.month - 1) + months * delta
    y, m = divmod(total, 12)
    m += 1
    return d.replace(year=y, month=m, day=min(d.day, calendar.monthrange(y, m)[1])).isoformat()


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
