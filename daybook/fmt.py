"""Date and time strings the user reads.

Two functions, in one place, because they were written three times: `hhmm` in the
Body tab, in `summary.py` and inline in `editline.py`; `human_date` in the Body tab
and the Summary tab. Not a DRY point — a correctness one. `human_date` raises
`ValueError` on a malformed date, and a malformed date reaching it is exactly how a
cloned `g` handler crashed the app. One copy means one place to harden.

Lives at package level rather than under `tui/` because `summary.py` needs it and
the data layer must not import the UI layer.
"""

from __future__ import annotations

import datetime as dt


def hhmm(ts: int) -> str:
    """A stored epoch-second timestamp as a wall clock, in local time."""
    return dt.datetime.fromtimestamp(int(ts)).strftime("%H:%M")


def human_date(date: str) -> str:
    """An ISO date as `Fri Aug 28`."""
    return dt.date.fromisoformat(date).strftime("%a %b %d")
