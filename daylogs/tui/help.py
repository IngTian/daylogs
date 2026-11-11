"""The `?` overlay: every key, grouped by kind, generated from KEYMAP.

Generated rather than written, so a key can never be bound-but-undocumented.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from daylogs.tui import keymap as km
from daylogs.tui.footer import glyph
from daylogs.tui.widgets import esc

_TITLES = {
    "nav": "Move around",
    "view": "Change the view",
    "write": "Record something",
    "danger": "Undo and delete",
}
_SCOPE_NOTE = {
    "app": "",
    "body": "  (Body)",
    "money": "  (Money)",
    "summary": "  (Summary)",
}


class HelpScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "close", "close"),
        Binding("question_mark", "close", "close"),
        Binding("q", "close", "close"),
    ]

    def compose(self) -> ComposeResult:
        """Two columns, because every key in one column pushes the write keys below
        the fold on a 40-row terminal — the help is useless if the half you came
        looking for needs scrolling to find. (No literal count here: the one that
        used to be written down had already drifted from `len(KEYMAP)`.)

        **Two columns are not enough, and no arrangement is.** Measured: the groups are 17 /
        15 / 14 / 5 rows, 51 in total. Every contiguous two-way split was enumerated —
        `[nav] | rest` is 17/34, the current `[nav, view] | [write, danger]` is 32/19, and
        `[nav, view, write] | [danger]` is 46/5 — so the split in use is already the best
        one at a 32-row tallest column. 51 rows cannot fit a 24-row terminal, and it still
        scrolls by 13 at the canonical 100x30. Under `-narrow` the columns stack, which
        takes the virtual height to 53 against a 16-row body at 80x24: the title, "Move
        around", and nav keys, with nothing on screen suggesting the other 37 rows exist.
        That impression — rather than the layout — is the defect, so the footer says when
        there is more. Reordering the groups was the obvious alternative and is wrong: of
        the keys that appear *only* here and not in the footer, nav holds 7 and view 3
        against write's 1, so the current order front-loads the half you came for.
        """
        groups = list(km.help_groups().items())
        half = (len(groups) + 1) // 2
        with VerticalScroll(id="help-body"):
            yield Static("daylogs keys", classes="pane-title")
            with Horizontal(id="help-columns"):
                for column in (groups[:half], groups[half:]):
                    yield Static(_render_column(column), classes="help-col")
            yield Static("esc or ? to close", classes="muted", id="help-foot")

    def on_mount(self) -> None:
        """Say so when the overlay scrolls, and only then.

        Deferred because `max_scroll_y` is 0 until the body has been laid out, and read
        from the widget rather than computed from a row count so it cannot drift from what
        the terminal is actually showing. A terminal tall enough to hold all 51 rows gets
        no hint it does not need.
        """
        self.call_after_refresh(self._note_scroll)

    def _note_scroll(self) -> None:
        body = self.query_one("#help-body", VerticalScroll)
        if body.max_scroll_y > 0:
            self.query_one("#help-foot", Static).update(
                "esc or ? to close · ↑↓ pgup pgdn for the rest"
            )

    def action_close(self) -> None:
        self.app.pop_screen()


def _render_column(groups) -> str:
    """One column of the overlay, as content markup.

    Pad first, escape second. `[` is itself a key, and unescaped it opens a markup tag that
    swallowed its own row and the `]` row's glyph with it — so the one screen the README
    promises "can't be out of date" listed neither horizon key, the two this release
    redefined. `footer._hint` escapes for exactly this reason and says so in a comment; the
    fix never reached here.

    The order matters and is the general rule: markup goes on *after* width arithmetic, so
    the 8-column field measures the glyph rather than the two characters of `\\[`.
    """
    lines: list[str] = []
    for kind, keys in groups:
        lines.append(f"[b]{_TITLES.get(kind, kind)}[/b]")
        for k in keys:
            cell = f"{glyph(k.key):<8}"
            lines.append(f"  {esc(cell)} {esc(k.label)}{_SCOPE_NOTE.get(k.scope, '')}")
        lines.append("")
    return "\n".join(lines)
