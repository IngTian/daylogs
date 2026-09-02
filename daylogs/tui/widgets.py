"""Pure text renderers.

No Textual imports here, so these unit-test as plain functions. That is the
reason the tabs stay thin: anything with a rule lives in a module with tests.
"""

from __future__ import annotations

_BLOCKS = "▁▂▃▄▅▆▇█"
_FULL = "█"
_EMPTY = "·"
_MARKER = "┃"
_NO_SHARE = "—"


# Good/bad signalling. Named rather than inlined so one edit changes every
# surface, and so a reader can tell "over budget" from "gaining weight" without
# tracing a colour literal through three files.
#
# Drawn from categories.PALETTE rather than the ANSI names: bare "red"/"green"
# resolve to #ff0000 and #008000, which are respectively harsh and nearly
# unreadable on this app's dark warm-earth background. These are the same three
# hues already used for the restaurant, education and grocery categories.
GOOD = "#63af7b"
BAD = "#cc5131"
WARN = "#dc9142"
FAINT = "dim"


def esc(text: str) -> str:
    """Escape text for Textual's content markup.

    `rich.markup.escape` is the wrong tool: it only escapes a `[` that begins
    something tag-shaped, so it hands back a bare `[` untouched — and Textual then
    reads it as the start of a tag. Verified against `Content.from_markup`: a
    backslash is what it wants, and `[[` is not an escape here.

    Anything that reaches markup and is not a literal in this repo needs this: a
    key glyph (`[` is a key), a filter string, a category slug from config.
    """
    return text.replace("\\", "\\\\").replace("[", "\\[")


def mark(text: str, style: str = "") -> str:
    """Wrap `text` in Rich markup.

    Always applied *after* any width arithmetic. Markup characters count toward
    `len()`, so colouring a line before truncating it silently sheds real content
    — which is why the bar builders below stay pure text and callers colour whole
    finished lines.
    """
    return f"[{style}]{text}[/]" if style else text


def trend_style(value: float | None, *, falling_is_good: bool = True) -> str:
    """Which way is good, for a signed number. The one place that rule lives.

    For a weight change or a calorie net, **down is good** — an assumption, and
    the only one available, since daylogs stores no goal weight and no target
    intake. Losing reads as progress for the person who built a weight tracker.
    For money remaining, the sign flips: more left is better, hence the keyword.

    Centralised because the rule was written out at each call site, and this repo
    has already been bitten by a rule cloned per caller (see
    `horizon.resolve_goto`). Formatting stays with the caller — the Day panel is
    tighter than the Body tab and renders the same delta differently on purpose —
    so what is shared is the judgement, not the layout.

    Zero is neither: an unchanged number should not be flagged as a win or a loss.
    """
    if value is None or value == 0:
        return ""
    good = value < 0 if falling_is_good else value > 0
    return GOOD if good else BAD


def sparkline(values: list[float], width: int = 24, *, from_zero: bool = False) -> str:
    """`from_zero` scales against 0..max instead of min..max.

    Fitting a series to its own min made a steady spend read as *nothing spent*:
    six months of level rent all landed on the lowest glyph, so the
    second-largest category rendered as an empty floor. Anything that is a
    magnitude from zero — spend, calories — wants the zero baseline; a series that
    only makes sense relative to itself, like body weight, does not.
    """
    if not values:
        return ""
    vals = values[-width:]
    lo, hi = (0.0, max(vals)) if from_zero else (min(vals), max(vals))
    lo = min(lo, min(vals))
    span = hi - lo
    if span == 0:
        # A flat series has no shape. Sit it mid-scale rather than on the floor,
        # which would claim a zero that isn't there.
        return (_BLOCKS[0] if hi == 0 else _BLOCKS[len(_BLOCKS) // 2]) * len(vals)
    return "".join(
        _BLOCKS[min(int((v - lo) / span * len(_BLOCKS)), len(_BLOCKS) - 1)] for v in vals
    )


def wide_sparkline(values: list[float], *, width: int, from_zero: bool = False) -> str:
    """A sparkline stretched to `width` cells by repeating each sample.

    Six monthly values in six cells read as noise at a terminal font size — the
    glyphs are one character wide and the eye has nothing to latch onto. Giving
    each month a multi-cell block turns the same data into legible steps. Repeated
    rather than interpolated, so every cell shows an observation that exists.
    """
    if not values or width <= 0:
        return ""
    base = sparkline(values, width=len(values), from_zero=from_zero)
    if not base:
        return ""
    return "".join(base[min(i * len(base) // width, len(base) - 1)] for i in range(width))


def burn_bar(
    spent: float, budget: float, *, width: int = 40, marker_frac: float | None = None
) -> str:
    """A budget-burn bar with an optional calendar-progress marker.

    The marker is the whole point: 84% of budget spent on day 27 of 31 is
    fine, and the same number on day 12 is not. A bar without the marker
    invites the wrong read.
    """
    filled = 0 if budget <= 0 else min(int(round(spent / budget * width)), width)
    filled = max(filled, 0)
    cells = [_FULL] * filled + [_EMPTY] * (width - filled)
    if marker_frac is not None:
        i = min(max(int(round(marker_frac * width)), 0), width - 1)
        cells[i] = _MARKER
    return "".join(cells)


# Width of everything after the bar, per builder: the amount columns, the
# separators and the flag. Used to decide how much room the bar may take.
_RANKED_TAIL = 1 + 6 + 1 + 10      # " " + pct + " " + right-aligned amount
# The pct field is 6 wide, not 5: "43.7%" is five characters but "100.0%" is six,
# and the bar has to be one width for every row or the columns stop lining up.
_BUDGET_TAIL = 1 + 9 + 2 + 9 + 2   # " " + spent + " /" + budget + flag


def _fit_bar(width: int, label_width: int, tail: int, wanted: int) -> int:
    """How many bar cells fit once the label and the numbers are paid for.

    Returns 0 rather than a stub when there is no room: a two-cell bar carries no
    information and just steals columns from the figures.
    """
    room = width - label_width - tail
    return 0 if room < 4 else min(wanted, room)


def money(value: float) -> str:
    return f"{value:,.2f}"


def signed(value: float) -> str:
    return f"{value:+,.2f}"


def ranked_bars(
    items: list[tuple[str, float]],
    *,
    width: int,
    label_width: int = 14,
    bar_width: int = 16,
) -> list[str]:
    """`label ████ 43.7%  1,517.91`, one line per item, ordered as given.

    This is the part-to-whole form for a terminal. A pie needs one distinguishable
    fill per category and a terminal has about eight, so a ninth category becomes
    ambiguous — and you still need a legend to read any amount. These lines carry
    label, share, amount and rank at once.

    Shares are of **gross** spend, not of the signed net. A category can go net
    negative when a refund lands (a reimbursed bill, a returned order), and
    dividing by the signed sum then inflates every other share past 100% — the
    denominator shrank by the refund. Such a row keeps its amount and shows no
    share, because a part-to-whole has no meaningful negative slice.
    """
    total = sum(v for _, v in items if v > 0) or 1.0
    # The bar yields to the numbers when the panel is narrow. Truncating the line
    # instead cut the amount column off entirely at a 42-column panel, leaving a
    # bar and a percentage — the two things you can estimate by eye — and dropping
    # the one thing you cannot.
    bar_width = _fit_bar(width, label_width, _RANKED_TAIL, bar_width)
    out: list[str] = []
    for name, value in items:
        label = name[: label_width - 1].ljust(label_width)
        if value > 0:
            share = value / total
            filled = min(max(1, round(share * bar_width)), bar_width)
            pct = f"{share * 100:4.1f}%"
        else:
            filled = 0
            pct = f"{_NO_SHARE:>5}"
        bar = _FULL * filled + " " * (bar_width - filled)
        out.append(f"{label}{bar} {pct} {money(value):>10}")
    return [line[:width] for line in out]


def budget_bars(
    items: list[tuple[str, float, float]],
    *,
    width: int,
    label_width: int = 14,
    bar_width: int = 14,
) -> list[str]:
    """`label ███████░░░ 412/500 ⚠` — spent against its own budget.

    Each bar is scaled to that category's own cap, not to the largest category, so
    "how close am I to this limit" is readable per row. Over-budget rows carry the
    ⚠ glyph, never colour alone.

    `filled` is clamped at both ends. A net-negative spend (a refund larger than
    the month's charges) drove it to -44 of 14 cells, and `_EMPTY * (14 - -44)`
    then emitted a 58-character bar that pushed the amounts past the line's width
    and off the panel — the row rendered as bare dots with no numbers at all.
    """
    bar_width = _fit_bar(width, label_width, _BUDGET_TAIL, bar_width)
    out: list[str] = []
    for name, spent, budget in items:
        if budget > 0:
            frac = spent / budget
            filled = min(max(int(round(frac * bar_width)), 0), bar_width)
            bar = _FULL * filled + _EMPTY * (bar_width - filled)
            flag = " ⚠" if spent > budget else "  "
            tail = f"{money(spent):>9} /{money(budget):>9}{flag}"
        else:
            bar = _EMPTY * bar_width
            # Right-align the placeholder in the same 9 columns the amount uses,
            # so a budgeted row and an unbudgeted one line up. A hand-counted run
            # of spaces here was one short and skewed the whole column.
            tail = f"{money(spent):>9} /{_NO_SHARE:>9}  "
        label = name[: label_width - 1].ljust(label_width)
        out.append(f"{label}{bar} {tail}")
    return [line[:width] for line in out]
