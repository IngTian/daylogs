"""The contextual key footer, rendered from the keymap.

Nothing here decides what the keys are — it reads KEYMAP. That is why the footer
cannot name a key that isn't bound, which is the failure mode of a hand-written
footer.

Four rows. Row 1 carries state — what you are looking at, how it is sorted, what is
filtered — and then one row per group of keys: what writes, what changes the view, what
gets you around.

Nineteen hints on a single line is a wall: every key looks equally important and finding
one means reading all of them. Grouping them on that one line and colour-coding the groups
was the first attempt, and it was not enough — Body still rendered 189 cells of hints in a
row, which is what the grouping was supposed to prevent.

Same height on every tab, whether or not a scope's groups would have fitted on fewer
lines. The alternative — collapse when it fits — makes the footer's height depend on which
tab you are on, so every tab switch reflows the table above it for a couple of rows of
screen. A predictable frame is worth more than those rows.
"""

from __future__ import annotations

from textual.widgets import Static

from daylogs.tui import keymap as km
from daylogs.tui.widgets import BAD, FAINT, esc

_GLYPH = {
    "left_square_bracket": "[",
    "right_square_bracket": "]",
    "question_mark": "?",
    "slash": "/",
    "plus": "+",
    # `=` is the same physical key as `+` without shift, and it is `footer=False`, so it
    # only ever renders in the `?` overlay — which is why it went a release showing the raw
    # Textual name `equals_sign`, the exact absurdity this table exists to prevent.
    "equals_sign": "=",
    "minus": "-",
    "shift+tab": "S-tab",
    "escape": "esc",
    "enter": "↵",
}

# One hue per group, so "this writes something" and "this only changes the view"
# are distinguishable before you have read a single label. Same palette as the
# good/bad signals rather than a second set of colours to learn.
_KIND_STYLE = {
    "write": "#67acb9",
    "view": "#9d81b8",
    "danger": BAD,
    "nav": FAINT,
}

# Actions first (including the destructive ones — deleting belongs with writing,
# not with navigation), then view controls, then getting-around. Putting `danger`
# last also pushed `x delete`/`u undo` past `q quit`, which reads as an
# afterthought. A group is only drawn if the active scope has keys in it.
_GROUPS: tuple[tuple[str, ...], ...] = (("write", "danger"), ("view",), ("nav",))

_SEP = " · "


def glyph(key: str) -> str:
    """Textual's key names are for code; `left_square_bracket` in a footer would
    be absurd."""
    return _GLYPH.get(key, key)


def _hint(k: km.Key) -> tuple[str, str]:
    """(plain, styled) for one key.

    Both, because markup characters count toward `len()`. Measuring the styled
    string would make every fit check wrong by the length of its colour codes and
    silently drop keys that would have fitted.
    """
    plain = f"{glyph(k.key)} {k.label}"
    style = _KIND_STYLE.get(k.kind, "")
    # Escape the glyph: `[` is itself a key here, and unescaped it opens a markup
    # tag — `[#7faab2][[/] prev` rendered as "[[/] prev", so the hint for `[` was
    # the one hint guaranteed to be mangled.
    styled = (
        f"[{style}]{esc(glyph(k.key))}[/] {esc(k.label)}" if style else esc(plain)
    )
    return plain, styled


def render_keys(scope: str, width: int, live=None) -> str:
    """Grouped, colour-coded key hints that fit `width` columns.

    Drops whole hints from the *end* when short of room — the tab's own verbs sit
    first and are what you came for, so shedding navigation before them is the
    right order. Pinned keys (`?` and `q`) always survive: `?` is how you discover
    everything else and `q` is how you leave, so dropping them first — which
    right-truncation does, since they sit last — is exactly backwards.
    """
    keys = km.footer_keys(scope)
    # A key with no handler in this scope is not a key. `live` is the app's own
    # action resolver, so the footer and the dispatcher always agree.
    if live is not None:
        keys = tuple(k for k in keys if live(k.action) is not None)
    by_kind: dict[str, list[km.Key]] = {}
    for k in keys:
        by_kind.setdefault(k.kind, []).append(k)

    groups: list[list[km.Key]] = []
    for kinds in _GROUPS:
        members = [k for kind in kinds for k in by_kind.get(kind, [])]
        if members:
            groups.append(members)

    def fit(members: list[km.Key]) -> list[km.Key]:
        """Drop hints from the end of ONE group until that line fits.

        Per line, not across the footer: each group has its own row now, so they no
        longer compete for room and a global order would be meaningless. It also fixes
        what the flat version got wrong the moment the groups were split — it shed from
        the end of the whole list, so an over-wide *first* group could not shrink at all
        until every later group had been emptied, and the write row overflowed a narrow
        terminal while the nav row sat empty beneath it.

        A pinned key is never dropped: `?` is how you find everything else and `q` is how
        you leave.
        """
        keep = list(members)
        while keep and len(_SEP.join(_hint(k)[0] for k in keep)) > width:
            droppable = [i for i, k in enumerate(keep) if not k.pin]
            if not droppable:
                # Even the pinned keys do not fit. Drop the whole line rather than
                # overflow it: at a width where `? keys` cannot be drawn there is nothing
                # useful to show, and a line wider than the terminal corrupts the layout
                # below it. `render_keys` then returns "" for an absurd width, which is
                # what it has always done.
                return []
            keep.pop(droppable[-1])
        return keep

    lines = []
    for g in groups:
        members = fit(g)
        if members:
            lines.append(_SEP.join(_hint(k)[1] for k in members))
    return "\n".join(lines)


class KeyFooter(Static):
    def __init__(self) -> None:
        super().__init__("", id="keyfooter", classes="keys")
        self._scope = "body"
        self._extra = ""
        self._live = None

    def on_resize(self, event) -> None:
        """Re-render on the widget's own resize. `Resize` is delivered to widgets,
        not to the App, so an App-level handler never fires — and the footer sheds
        keys to fit, so a stale width means wrong content."""
        self.update_for(self._scope, self._extra, self._live)

    def update_for(self, scope: str, extra: str = "", live=None) -> None:
        """`extra` is the tab's state row: range, sort, filters. It gets its own
        line so the keys below are never competing with it for space.

        The app's width is the fallback because `self.size` is still 0 during
        on_mount, before the first layout: guessing narrow there silently drops
        keys that would have fitted.
        """
        self._scope, self._extra, self._live = scope, extra, live
        width = self.size.width or getattr(self.app, "size", None) and self.app.size.width
        width = width or 100
        keys = render_keys(scope, max(width - 2, 10), live)
        self.update(f"{extra}\n{keys}" if extra else f"\n{keys}")
