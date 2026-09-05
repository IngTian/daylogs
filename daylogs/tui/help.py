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
        used to be written down had already drifted from `len(KEYMAP)`.)"""
        groups = list(km.help_groups().items())
        half = (len(groups) + 1) // 2
        with VerticalScroll(id="help-body"):
            yield Static("daylogs keys", classes="pane-title")
            with Horizontal(id="help-columns"):
                for column in (groups[:half], groups[half:]):
                    yield Static(_render_column(column), classes="help-col")
            yield Static("esc or ? to close", classes="muted")

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
