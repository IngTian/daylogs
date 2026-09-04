"""Date and time strings the user reads.

Written in one place because they were written multiple times independently: `hhmm`
in the Body tab and in `summary.py`; `human_date` in the Body tab and the Summary
tab. Not a DRY point — a correctness one. `human_date` raises `ValueError` on a
malformed date, and a malformed date reaching it is exactly how a cloned `g` handler
crashed the app. One copy means one place to harden.

Lives at package level rather than under `tui/` because `summary.py` needs it and
the data layer must not import the UI layer.

**The zone is an argument, never a default.** These used to read the *machine's* zone
while every parser resolved `@HH:MM` in `cfg.timezone`, so on a machine whose zone
differed from the configured one an edit's prefill round-trip moved the row by the
offset. A default is how that hid: every call site looked right. Requiring the zone
means a caller that has not thought about it does not compile.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo


def wall(ts: int, tz: str) -> dt.datetime:
    """A stored epoch-second timestamp as wall-clock time in `tz`.

    Takes a zone *name* rather than a tzinfo so daylight saving is resolved per
    timestamp: a captured fixed offset would render a January reading with August's
    offset, an hour out.
    """
    return dt.datetime.fromtimestamp(int(ts), ZoneInfo(tz))


def hhmm(ts: int, tz: str) -> str:
    """A stored epoch-second timestamp as a wall clock in `tz`."""
    return wall(ts, tz).strftime("%H:%M")


def human_date(date: str) -> str:
    """An ISO date as `Fri Aug 28`."""
    return dt.date.fromisoformat(date).strftime("%a %b %d")
