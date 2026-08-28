"""The footer inline prompt.

Every write goes through one line of text rather than a modal form. That is
the whole friction argument: a weigh-in is `w`, then `78.2`, then enter.

Submission rides Textual's native `Input.Submitted`, so the only keys handled
here are the ones Input does not already own: escape to cancel and up/down to
walk history. History is per-label, so `↑` in the expense prompt recalls
expenses rather than weights.
"""

from __future__ import annotations

from collections import defaultdict, deque

from textual.message import Message
from textual.widgets import Input

from daybook.tui import hints

_HISTORY = 50


class InlinePrompt(Input):
    class Cancelled(Message):
        def __init__(self, label: str) -> None:
            super().__init__()
            self.label = label

    def __init__(self) -> None:
        super().__init__(id="prompt")
        self.display = False
        self.label = ""
        self.error = ""
        self._history: dict[str, deque[str]] = defaultdict(lambda: deque(maxlen=_HISTORY))
        self._idx = 0

    @property
    def is_open(self) -> bool:
        return bool(self.display)

    def open(self, label: str, prefill: str = "") -> None:
        self.label = label
        self.value = prefill
        self.display = True
        self._idx = len(self._history[label])
        self.clear_error()
        self.focus()

    def close(self) -> None:
        self.value = ""
        self.display = False
        self.label = ""
        # After clearing the label, so the slots are blanked rather than repainted
        # with the label that is going away.
        self.clear_error()

    def show_error(self, message: str) -> None:
        """Keep the text; say why it was rejected.

        The message goes in the border *subtitle*, taking the grammar's place. Not
        the placeholder: Textual renders a placeholder only while the input is
        empty, and the whole point of this feature is that the text stays, so a
        placeholder-only error is invisible exactly when it is needed. Not the
        border title either — that now holds the label, which you still want while
        reading the error.
        """
        self.error = message
        self.border_subtitle = message
        self.add_class("error")

    def clear_error(self) -> None:
        """Restore the three-slot layout: label above, example inside, grammar below.

        The label used to *be* the placeholder, so it vanished on the first
        keystroke and there was never room for an example — you had to already know
        the grammar to use the prompt.
        """
        self.error = ""
        hint = hints.for_label(self.label)
        self.border_title = f"{self.label} ›" if self.label else ""
        self.border_subtitle = hint.grammar if hint else ""
        self.placeholder = hint.example if hint else ""
        self.remove_class("error")

    def remember(self, label: str, text: str) -> None:
        if text:
            self._history[label].append(text)

    def on_key(self, event) -> None:
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            label = self.label
            self.close()
            self.post_message(self.Cancelled(label))
            return
        if event.key in ("up", "down"):
            event.stop()
            event.prevent_default()
            hist = self._history[self.label]
            if not hist:
                return
            step = -1 if event.key == "up" else 1
            self._idx = min(max(self._idx + step, 0), len(hist))
            self.value = hist[self._idx] if self._idx < len(hist) else ""
