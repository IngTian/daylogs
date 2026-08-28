"""Behaviour shared by the two tabs that draw width-sensitive panels.

Both concerns here are the same concern — a panel's contents are built to its own
measured width, so they have to be rebuilt when that width changes — and both were
written twice (three times for the width probe, with three different floor values
and the same magic fallback).

Kept to exactly that. `focus_default`, the cursor-bounds check and the prompt
dispatch chain are also near-identical between the tabs, and are deliberately
*not* here: they are one or two lines each, and a one-line override that you can
read in place beats an inherited one you have to go and find.
"""

from __future__ import annotations

from textual.containers import Vertical

# Wide enough to be worth drawing into before the first layout has happened.
_FALLBACK = 46


class PanelTab(Vertical):
    """A tab whose panels size their own contents."""

    def on_resize(self, event) -> None:
        """`Resize` is delivered to widgets, not to the App, so an App-level handler
        never fires — each tab has to ask for its own redraw."""
        self.reload()

    def panel_width(self, selector: str, *, minimum: int) -> int:
        """The usable width inside a panel, measured from the panel itself.

        A constant wider than the panel makes every row wrap, which doubles the
        panel's height and looks broken. `content_size` is 0 before the first
        layout, hence the fallback and the app's one `call_after_refresh` redraw.
        """
        try:
            avail = self.query_one(selector).content_size.width
        except Exception:  # noqa: BLE001 - before the first layout there is no size
            avail = 0
        return max(minimum, avail or _FALLBACK)
