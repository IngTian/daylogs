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

from daylogs.complete import complete
from daylogs.tui import hints
from daylogs.tui.widgets import esc

_HISTORY = 50


class InlinePrompt(Input):
    class Cancelled(Message):
        """Carries the owner as well as the label, because `close()` clears both and the
        app needs to disarm the tab the prompt belonged to — not the one on screen."""

        def __init__(self, label: str, owner: str = "") -> None:
            super().__init__()
            self.label = label
            self.owner = owner

    def __init__(self) -> None:
        super().__init__(id="prompt")
        self.display = False
        self.label = ""
        # The tab that opened this prompt. Its answer belongs to that tab even if another
        # one is on screen when it arrives — see `open`.
        self.owner = ""
        self.error = ""
        self._history: dict[str, deque[str]] = defaultdict(lambda: deque(maxlen=_HISTORY))
        self._idx = 0
        self._cycle = 0
        self._cycle_from: tuple[str, str, int] | None = None

    @property
    def is_open(self) -> bool:
        return bool(self.display)

    def open(self, label: str, prefill: str = "", *, owner: str = "") -> None:
        """Show the prompt, and remember which tab it belongs to.

        The owner matters because two prompts are opened by a *worker*, not a keypress:
        `confirm food` and `confirm activity` arrive up to a minute after `f`/`a`, by which
        time the user may be looking at another tab — which the in-progress popup exists to
        make comfortable. Routing the answer to whatever was on screen handed it to a tab
        with no branch for that label and no `else`, so `enter` closed the prompt and wrote
        nothing: no row, no toast, and no way back, since `show_scope` refuses to switch
        while a prompt is open. A prompt opened by a keypress cannot be mis-routed for that
        same reason, so this only ever corrects the asynchronous pair.
        """
        self.owner = owner or self.app.scope
        self.label = label
        self.value = prefill
        self.display = True
        self._idx = len(self._history[label])
        self._cycle = 0
        self._cycle_from = None
        self.clear_error()
        self.focus()

    def close(self) -> None:
        self.value = ""
        self.display = False
        self.label = ""
        self.owner = ""
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
        # Escaped: error text quotes what you typed — `parse_profile` interpolates the
        # rejected word verbatim — so this slot is a markup sink fed by the keyboard.
        self.border_subtitle = esc(message)
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

    def show_candidates(self, candidates: list[str]) -> None:
        """Candidates take the grammar's slot while the cursor is in a completable
        token. Reusing that slot is why completion costs no screen space and needs
        no overlay."""
        self.border_subtitle = (
            " ".join(esc(c) for c in candidates) if candidates else "no match"
        )

    def complete_now(self, vocab: dict[str, tuple[str, ...]]) -> None:
        """Apply one tab press. Repeated presses on an untouched token cycle.

        Cycling replays the line the first press started from, rather than
        re-completing the line that press produced. It has to: the first press
        overwrites the typed prefix with a whole candidate, so re-deriving the
        prefix would match only that candidate and tab would stand still on it.
        """
        if self._cycle_from is not None and self._cycle_from[0] == self.value:
            _, line, cursor = self._cycle_from
            self._cycle += 1
        else:
            line, cursor, self._cycle = self.value, self.cursor_position, 0
        result = complete(line, cursor, vocab, cycle=self._cycle)
        if result is None:
            self._cycle_from = None
            return
        self.value = result.text
        self.cursor_position = result.cursor
        # Armed only while there is somewhere else to go. Any keystroke moves
        # `value` off the remembered text, so a session drops itself.
        self._cycle_from = (result.text, line, cursor) if len(result.candidates) > 1 else None
        self.refresh_candidates(vocab)

    def refresh_candidates(self, vocab: dict[str, tuple[str, ...]]) -> None:
        """Called on every change: show candidates in a sigil token, the grammar
        elsewhere."""
        if self.error:
            return
        result = complete(self.value, self.cursor_position, vocab)
        if result is None:
            hint = hints.for_label(self.label)
            self.border_subtitle = hint.grammar if hint else ""
        else:
            self.show_candidates(list(result.candidates))

    def on_key(self, event) -> None:
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            label, owner = self.label, self.owner
            self.close()
            self.post_message(self.Cancelled(label, owner))
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
