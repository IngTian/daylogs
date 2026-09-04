"""Braille line charts. Pure functions; no Textual import, so they unit-test as
plain functions the way widgets.py does.

A braille cell packs 2x4 dots, so an 8-row by 48-column chart carries 96x32 dot
resolution — roughly 12x a one-row, 8-level sparkline.

Time windows live in horizon.py, shared with the Money tab.

**A line, not bars.** Weight moves inside a narrow band (a real series spans
70–75 kg). A bar or filled-area mark implies a meaningful zero baseline;
anchored at the series minimum it renders as a solid mass whose only legible
feature is its top edge. A line carries the trajectory and implies no baseline,
so a fitted y-range is honest. Bars remain correct for spend, which really is a
magnitude from zero.
"""

from __future__ import annotations

from itertools import pairwise

BLANK = 0x2800
# dot bit for [row_within_cell][column_within_cell]
_DOTS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))

def braille_line(
    values: list[float],
    *,
    width: int,
    height: int,
    positions: list[float] | None = None,
    low: float | None = None,
    high: float | None = None,
) -> list[str]:
    """`height` rows of `width` braille cells, top row first.

    `positions` places each value at a fraction of the width, so a series can be
    plotted against real time. Without it, points are spaced evenly by index —
    which silently rescales the x-axis to the *number of samples*, so two readings
    a day apart drew a smooth month-long climb across a month-wide panel. Any
    caller plotting a dated series should pass positions; the index default is for
    genuinely undated series.

    `low`/`high` override the vertical extent, which the series otherwise derives from
    itself. A self-fitted range is right for weight — it only means anything relative
    to itself — and wrong for a signed series, where the reader needs to see where zero
    falls. A value outside the given extent is clipped by `plot`, not an error.
    """
    grid = [[0] * max(width, 0) for _ in range(max(height, 0))]
    if not values or width <= 0 or height <= 0:
        return ["".join(chr(BLANK + c) for c in row) for row in grid]

    dot_w, dot_h = width * 2, height * 4
    lo = min(values) if low is None else low
    hi = max(values) if high is None else high
    span = (hi - lo) or 1.0

    last = max(len(values) - 1, 1)
    pts: list[tuple[int, int]] = []
    for i, v in enumerate(values):
        if positions is not None and i < len(positions):
            frac = min(max(positions[i], 0.0), 1.0)
        else:
            frac = i / last if len(values) > 1 else 0.0
        px = int(frac * (dot_w - 1))
        py = int((1 - (v - lo) / span) * (dot_h - 1))
        pts.append((px, py))

    def plot(px: int, py: int) -> None:
        if 0 <= px < dot_w and 0 <= py < dot_h:
            grid[py // 4][px // 2] |= _DOTS[py % 4][px % 2]

    if len(pts) == 1:
        plot(*pts[0])
    for (x0, y0), (x1, y1) in pairwise(pts):
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for s in range(steps + 1):
            plot(round(x0 + (x1 - x0) * s / steps), round(y0 + (y1 - y0) * s / steps))

    return ["".join(chr(BLANK + c) for c in row) for row in grid]


def _zero_row(lo: float, hi: float, height: int) -> int | None:
    """Which chart row holds the value 0, when that needs marking.

    `None` unless zero falls *strictly inside* the extent. When it lands on the top or
    bottom row the extent label already reads `0`, and a rule there would say the same
    thing twice.
    """
    if not lo < 0 < hi or height < 3:
        return None
    dot_h = height * 4
    row = int((1 - (0 - lo) / ((hi - lo) or 1.0)) * (dot_h - 1)) // 4
    return row if 0 < row < height - 1 else None


def frame_chart(
    values: list[float],
    *,
    width: int,
    height: int,
    ylabel_width: int = 6,
    x_labels: tuple[str, ...] = (),
    unit: str = "",
    positions: list[float] | None = None,
    include_zero: bool = False,
    low: float | None = None,
    high: float | None = None,
) -> list[str]:
    """Chart rows plus a y-axis, an axis rule, and an x-label row.

    The y labels describe the extent of `values` as passed in — the caller's
    window. v1 plotted the last 30 entries while labelling min/max as though they
    described the requested window, which made the chart quietly wrong.

    `low`/`high` override that extent, for a caller whose *window* holds more than it
    draws. The weight chart plots one point per day but a day may hold several readings,
    so fitting to the drawn points labelled the top of a week as 81.85 when a reading of
    82.65 sat inside it — the same defect one level up. The consequence is that the line
    then does not touch the panel edges, which is the honest picture: the value defining
    the edge is not one of the points on screen.

    `include_zero` pulls 0 into that extent, for a series whose sign is the point.
    A signed net fitted to its own min and max is unreadable: a month of deficits and
    a month of surpluses draw the identical picture. Pulling zero in fixes all three
    cases at once — an all-deficit series gets `0` as its top label, an all-surplus one
    gets it at the bottom, and only a series that actually crosses zero needs a rule,
    which is drawn on the y-axis as `┼` rather than in braille. Braille dots would be
    indistinguishable from the data.
    """
    total = ylabel_width + 1 + width
    if not values:
        return [f"{'':>{ylabel_width}} │ no data yet".ljust(total)[:total]]

    hi = max(values) if high is None else high
    lo = min(values) if low is None else low
    if include_zero:
        hi, lo = max(hi, 0.0), min(lo, 0.0)
    zero = _zero_row(lo, hi, height) if include_zero else None
    rows: list[str] = []
    plotted = braille_line(
        values, width=width, height=height, positions=positions, low=lo, high=hi
    )
    for i, line in enumerate(plotted):
        if i == 0:
            label = f"{hi:g}{unit}"
        elif i == height - 1:
            label = f"{lo:g}{unit}"
        elif i == zero:
            label = "0"
        else:
            label = ""
        rows.append(f"{label:>{ylabel_width}}{'┼' if i == zero else '│'}{line}")

    rows.append(f"{'':>{ylabel_width}}└{'─' * width}")

    label_row = [" "] * total
    if x_labels:
        # Spread the ticks across the full axis: the first flush left, the last
        # flush right, the rest proportional. Dividing by the label *count* put
        # the final tick two-thirds of the way along, so a three-tick axis looked
        # like it stopped early.
        axis_left = ylabel_width + 1
        gaps = max(len(x_labels) - 1, 1)
        for j, text in enumerate(x_labels):
            frac = j / gaps if len(x_labels) > 1 else 0.0
            start = axis_left + round(frac * (width - 1))
            if j == len(x_labels) - 1 and len(x_labels) > 1:
                start -= len(text) - 1
            start = min(max(start, axis_left), total - len(text))
            for o, ch in enumerate(text):
                if 0 <= start + o < total:
                    label_row[start + o] = ch
    rows.append("".join(label_row))
    return [r.ljust(total)[:total] for r in rows]
