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

Two entry points, because the two callers want opposite failure behaviour:
`resolve` for config (never stop the app over a cosmetic setting) and `check` for
typed input (object, so the prompt can keep the text and let you fix it).
"""

from __future__ import annotations

from textual.theme import BUILTIN_THEMES

# Chosen on evidence rather than taste: PALETTE's hues were tuned for a "dark
# warm-earth background", which is what gruvbox is, so the nine category colours
# sit in harmony with it instead of fighting it.
DEFAULT = "gruvbox"


class ThemeError(ValueError):
    pass


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


def check(name: str) -> str:
    """A usable theme name, for the typed path. Raises `ThemeError`.

    The opposite of `resolve` on purpose: silently substituting a theme after
    someone typed one would look like the keypress was swallowed.
    """
    cleaned = name.strip()
    if cleaned not in BUILTIN_THEMES:
        raise ThemeError(f"{cleaned!r} is not a theme — tab completes the list")
    return cleaned
