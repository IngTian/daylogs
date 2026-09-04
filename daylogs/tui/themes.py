"""Theme names, borrowed from Textual rather than defined here.

`app.tcss` styles everything with Textual design tokens — `$surface`, `$accent`,
`$text`, `$text-muted`, `$panel-lighten-2`, `$error` — and carries no colour
literals at all. So `App.theme = name` re-themes every border, background and
muted line without a stylesheet change, and Textual's ~20 maintained themes come
for free. Defining our own set would be rebuilding a wheel.

What themes deliberately do *not* touch: `categories.PALETTE` and the good/bad/
warn signals. A category's colour is its identity — grocery being amber is a fact
about grocery, not about the chrome around it — and those hues were checked
against a warm dark theme, a cool dark theme and a light one before this shipped.

`resolve` is the only validator left. There used to be a `check` beside it that raised
instead of falling back, for a typed prompt — the two callers wanted opposite failure
behaviour, which was the right design for that prompt. `T` is a picker now and every name
it can produce came from `names()`, so there is no unvalidated input anywhere and a
validator with no caller is exactly the sort of thing that quietly rots.
"""

from __future__ import annotations

from textual.message import Message
from textual.theme import BUILTIN_THEMES
from textual.widgets import Static

# Chosen on evidence rather than taste: PALETTE's hues were tuned for a "dark
# warm-earth background", which is what gruvbox is, so the nine category colours
# sit in harmony with it instead of fighting it.
DEFAULT = "gruvbox"


def names() -> tuple[str, ...]:
    """Every theme on offer, sorted — completion presents them in this order.

    Read from Textual at call time rather than frozen into a literal here, so a
    Textual upgrade that adds a theme offers it without a code change.
    """
    return tuple(sorted(BUILTIN_THEMES))


def resolve(name: str | None) -> str:
    """A usable theme name, for the config path. Never raises.

    A stale or misspelled name in `config.toml` falls back to the default. The
    alternative — refusing to start — would be a cosmetic setting taking the whole
    app down, and the setting is one someone edits by hand.
    """
    if not name:
        return DEFAULT
    return name if name in BUILTIN_THEMES else DEFAULT





# ── the picker ───────────────────────────────────────────────────────────
# `T` used to open a text prompt with tab completion, and the reason written down at
# the time was that "cycling 21 themes one keypress at a time would take up to 21
# presses to get back to one you liked". That answered the wrong question: it assumed
# you already know which name you want, and the whole difficulty with a theme is that
# a name tells you nothing — you have to see it against the charts, the bars and the
# good/bad colours, which are deliberately *not* themed.
#
# So the picker previews. `←`/`→` apply each theme live, `enter` keeps the one on
# screen, `esc` puts back the one you started with — which is also the answer to the
# original objection, in one keypress rather than up to twenty-one.
#
# It is a focused widget in the bottom container, not a modal screen, for the reason
# the whole feature exists: a ModalScreen covers the interface you are previewing.

_SEP = "   "
# Literal marks, not colour: the cursor sits on a name whose own colours are changing
# under it, so highlighting is exactly the signal that cannot be trusted here.
_CURSOR = ("▸", "◂")
# Reserved for the two ellipses, always, so growing the window cannot overshoot the
# panel once they are added. Four columns of a hundred-odd is not worth the branch.
_ELLIPSIS_RESERVE = 4


def strip(names, index: int, width: int) -> str:
    """A window of theme names centred on `index`, as wide as `width` allows.

    Plain text, and the arithmetic happens here — the cursor is marked with characters
    rather than markup precisely so `len()` still measures what reaches the screen.

    Grows rightward first: the next name `→` will land on is the one most worth seeing,
    and at the start of the list there is nothing to the left anyway.
    """
    names = list(names)
    if not names:
        return ""
    index = max(0, min(index, len(names) - 1))
    marked = [f"{_CURSOR[0]}{n}{_CURSOR[1]}" if i == index else n for i, n in enumerate(names)]
    budget = max(len(marked[index]), width - _ELLIPSIS_RESERVE)

    lo = hi = index
    out = marked[index]
    while True:
        grew = False
        if hi + 1 < len(names) and len(out) + len(_SEP) + len(marked[hi + 1]) <= budget:
            hi += 1
            out = out + _SEP + marked[hi]
            grew = True
        if lo - 1 >= 0 and len(out) + len(_SEP) + len(marked[lo - 1]) <= budget:
            lo -= 1
            out = marked[lo] + _SEP + out
            grew = True
        if not grew:
            break

    if lo > 0:
        out = "… " + out
    if hi < len(names) - 1:
        out = out + " …"
    return out


class ThemePicker(Static):
    """`T`'s surface: a live preview you arrow through.

    Keys are captured in `on_key` with `stop()` + `prevent_default()`, the same way
    `InlinePrompt` takes `escape` and the history arrows. That is what makes `←`/`→`
    work at all: they are app-scope tab navigation, deliberately *not* priority
    bindings, so a focused widget's handler runs first and can claim them.

    The theme is applied on every step, so the app you are looking at *is* the preview.
    Cancelling restores whatever was in effect when the picker opened — not the value in
    `config.toml`, which may never have been written.
    """

    class Chosen(Message):
        def __init__(self, name: str) -> None:
            super().__init__()
            self.name = name

    class Cancelled(Message):
        pass

    can_focus = True

    def __init__(self, **kw) -> None:
        super().__init__("", **kw)
        self._names: tuple[str, ...] = ()
        self._index = 0
        self._restore = DEFAULT
        self.display = False

    @property
    def is_open(self) -> bool:
        return self.display

    @property
    def selected(self) -> str:
        return self._names[self._index] if self._names else DEFAULT

    def open(self, current: str) -> None:
        """Show the picker, positioned on the theme in effect.

        `names()` is read here rather than stored, for the reason it is a function: a
        Textual upgrade that adds a theme should offer it without a code change.
        """
        self._names = names()
        self._restore = current
        self._index = self._names.index(current) if current in self._names else 0
        self.display = True
        self.repaint()
        self.focus()

    def close(self) -> None:
        self.display = False

    def repaint(self) -> None:
        if not self._names:
            return
        width = self.content_size.width or 80
        self.update(strip(self._names, self._index, width))
        self.border_title = f"theme › {self.selected}   {self._index + 1} of {len(self._names)}"
        # Names the theme `esc` puts back, because that is the one thing you cannot see
        # once every colour on screen has changed.
        self.border_subtitle = f"← → preview · enter keeps it · esc restores {self._restore}"

    def on_resize(self) -> None:
        """The window is sized from the panel, like every other panel here — a width
        frozen at mount is wrong the first time the terminal is resized."""
        if self.display:
            self.repaint()

    def _step(self, delta: int) -> None:
        """Wraps, so the far end of the list is never more than half of it away."""
        self._index = (self._index + delta) % len(self._names)
        self.app.theme = self.selected
        self.repaint()

    def on_key(self, event) -> None:
        if not self.display:
            return
        if event.key in ("left", "right"):
            event.stop()
            event.prevent_default()
            self._step(-1 if event.key == "left" else 1)
        elif event.key == "enter":
            event.stop()
            event.prevent_default()
            name = self.selected
            self.close()
            self.post_message(self.Chosen(name))
        elif event.key == "escape":
            event.stop()
            event.prevent_default()
            self.app.theme = self._restore
            self.close()
            self.post_message(self.Cancelled())
