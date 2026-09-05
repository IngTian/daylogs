"""The contextual key footer, rendered from the keymap.

Nothing here decides what the keys are — it reads KEYMAP. That is why the footer
cannot name a key that isn't bound, which is the failure mode of a hand-written
footer.

Two rows, not one. Nineteen hints flattened into a single 190-character line is a
wall: every key looks equally important and finding one means reading all of them.
Row 1 carries state — what you are looking at, how it is sorted, what is filtered.
Row 2 carries the keys, grouped by what they do and colour-coded by group.
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
_GROUP_SEP = "   "


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

    pinned = [k for k in keys if k.pin]
    pinned_plain = _SEP.join(_hint(k)[0] for k in pinned)

    def assemble(drop: int) -> tuple[str, int]:
        """Render with the last `drop` unpinned hints removed."""
        flat = [k for g in groups for k in g]
        keep = {id(k) for k in flat[: len(flat) - drop]} | {id(k) for k in pinned}
        out_styled: list[str] = []
        out_plain: list[str] = []
        for g in groups:
            members = [k for k in g if id(k) in keep]
            if not members:
                continue
            out_styled.append(_SEP.join(_hint(k)[1] for k in members))
            out_plain.append(_SEP.join(_hint(k)[0] for k in members))
        return _GROUP_SEP.join(out_styled), len(_GROUP_SEP.join(out_plain))

    total = sum(len(g) for g in groups)
    for drop in range(total - len(pinned) + 1):
        styled, plain_len = assemble(drop)
        if plain_len <= width:
            return styled
    return pinned_plain if len(pinned_plain) <= width else ""


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
