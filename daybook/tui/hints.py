"""What each prompt accepts, as data.

The grammars in parse.py are compact and completely undiscoverable: pressing `h`
gave a bare `profile ›` and no indication that it wanted a height, a sex and a
birthday in any order. Knowing the grammar existed was not the same as being able
to use it.

Every prompt now shows three things, using the three slots the bordered input
already has and no extra screen rows:

    ╭─ profile › ───────────────────────────────────────╮
    │ 180 male 1990-01-01                               │   <- example, greyed
    ╰─ height · m/f · birthday — any order, partial ok ─╯   <- grammar, persistent

The example is the placeholder, so it disappears as soon as you type — which is
correct, it is scaffolding. The grammar is the border subtitle and stays put,
because that is the part you still want halfway through a line. An error replaces
the grammar and reddens the border.

`example` must be a genuinely valid line: it is copied verbatim by a reader, and a
test parses every one of them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Both are supported by every tokenize-based grammar; spelled out once here rather
# than repeated into each subtitle, where it would crowd out the fields.
WHEN = "@date · HH:MM"


@dataclass(frozen=True)
class Hint:
    label: str
    example: str
    grammar: str


HINTS: tuple[Hint, ...] = (
    # ── body ─────────────────────────────────────────────────────────────
    Hint("weigh", "78.2", f"kg · note (optional) · {WHEN}"),
    Hint(
        "food",
        "chicken salad 610",
        f"what you ate · kcal — omit the kcal and Claude estimates it · {WHEN}",
    ),
    Hint(
        "confirm food",
        "chicken salad 610",
        "Claude's estimate — fix the kcal if it looks wrong, then enter",
    ),
    Hint("photo path", "~/Downloads/lunch.jpg", "a path, or drag the file into the terminal"),
    Hint("profile", "180 male 1990-01-01", "height · m/f · birthday — any order, partial ok"),
    # ── money ────────────────────────────────────────────────────────────
    Hint(
        "expense",
        "12.40 lunch restaurant",
        f"amount · what · category — a negative amount is a refund · {WHEN}",
    ),
    Hint("budget", "500 grocery", "amount · name (defaults to the category) · category"),
    Hint(
        "recurring",
        "20.99 streaming subscriptions",
        "amount · name · category · monthly or annually",
    ),
    Hint("fix category", "restaurant", "a category — it went to other until you name one"),
    Hint("filter", "coffee", "text to match in a description · esc clears it"),
    # ── app ──────────────────────────────────────────────────────────────
    Hint("go to date", "2026-06-15", "a date, or 2026-06 for the whole month"),
    # ── editing an existing row ──────────────────────────────────────────
    # A different grammar from entry, and deliberately so: see editline.py. Fields
    # are separated so nothing can be stolen out of the free-text one.
    Hint(
        "edit weigh",
        "78.2 | post-run | 2026-08-27",
        "kg | note | date — drop a field to keep it, empty it to clear it",
    ),
    Hint(
        "edit food",
        "chicken salad | 610 | 2026-08-27 | 13:05",
        "what | kcal | date | time — drop a field to keep it",
    ),
    Hint(
        "edit expense",
        "12.40 | lunch | restaurant | 2026-08-27",
        "amount | what | category | date — drop a field to keep it",
    ),
    Hint(
        "edit recurring",
        "20.99 | Streaming | subscriptions | monthly",
        "cost | name | category | monthly or annually",
    ),
)

_BY_LABEL = {h.label: h for h in HINTS}


def for_label(label: str) -> Hint | None:
    return _BY_LABEL.get(label)


_OPEN_CALL = re.compile(r"prompt\.open\(\s*\"([^\"]+)\"")


def labels_in_source(text: str) -> set[str]:
    """Every prompt label opened in a chunk of source.

    Used by a test to fail when a new prompt ships without a hint — which is
    exactly how `profile` shipped. There is no table of labels to check against
    (they are string literals at the call sites), so the source is the register.
    """
    return set(_OPEN_CALL.findall(text))
