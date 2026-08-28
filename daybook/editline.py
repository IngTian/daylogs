"""The edit grammar: one line, fields separated by `|`.

Editing deliberately does NOT reuse the entry grammar, even though the original
spec assumed it would. The entry grammar is airy on purpose — `12.40 lunch
restaurant` needs no punctuation because the parser hunts for an amount, a known
category slug and a time token wherever they appear, and calls whatever is left
the description. That is lovely for typing and unsound for editing, because
rendering a stored row back into it lets the free-text field lose a token:

    note "weighed at 6:50 before food"  ->  note loses "6:50" AND the time becomes 06:50
    "lunch at grocery store" / restaurant  ->  category becomes grocery,
                                               description becomes "lunch at store restaurant"
    name "Insurance billed annually" / monthly  ->  name mangled AND cycle overwritten
    description "750"                    ->  rejected as numeric-only; row uneditable

Two fields corrupted by one keystroke, silently. Ordering the render to put the
slug first shields later slugs but cannot help a time token, and none of it helps
a name containing "annually". So edits get a grammar where a field is a whole
segment and nothing can be stolen from a neighbour.

Round-trip is by construction: `parse(render(row))` returns exactly the row's
values, for every one of the trap cases above. Tests assert that.

Two rules make the line forgiving:

- an **omitted** trailing segment leaves that field unchanged, so `81.5` alone is a
  quick weight correction that keeps the note and the date;
- a **provided but empty** segment clears that field, so `81.5 |  | 2026-08-27`
  deliberately removes the note.

Which fields appear is not arbitrary: each entity exposes exactly the columns its
table already shows. What you can see is what you can edit — and it keeps columns
with no visible representation (food's `source`, expense's `note`, recurring's
`active`, every `created_at`) out of the line, so an edit cannot silently rewrite
provenance.
"""

from __future__ import annotations

import datetime as dt

from daybook import money
from daybook.categories import slugs
from daybook.fmt import hhmm
from daybook.parse import MAX_KCAL, MAX_KG, TIME_RE, ParseError, to_amount

SEP = "|"
# A placeholder for an escaped separator while splitting. NUL cannot appear in
# input typed at a terminal prompt, so it needs no escaping of its own.
_PLACEHOLDER = "\x00"
# Imported, not restated: the two grammars have to agree about what a plausible
# value is, and about which cycles exist.
CYCLES = tuple(sorted(money.CYCLES))


def escape(text: str) -> str:
    return text.replace(SEP, "\\" + SEP)


def split_fields(raw: str) -> list[str]:
    """Segments of an edit line, honouring `\\|` as a literal pipe.

    Escaping rather than rejecting: a description containing a pipe is rare, but a
    row that cannot be edited at all is a dead end with no way out from inside the
    app.
    """
    swapped = raw.replace("\\" + SEP, _PLACEHOLDER)
    return [seg.replace(_PLACEHOLDER, SEP).strip() for seg in swapped.split(SEP)]


def join_fields(parts: list[str]) -> str:
    return f" {SEP} ".join(escape(p) for p in parts)


# ── coercion ─────────────────────────────────────────────────────────────
def _number(text: str, field: str) -> float:
    """Shared with the entry grammar, so a decimal comma is rejected in both.

    Stripping commas unconditionally turned `12,40` into 1240 — the same silent
    100x error, and an edit is exactly where someone retypes an amount.
    """
    try:
        return to_amount(text)
    except ParseError as err:
        raise ParseError(f"{field}: {err}") from None
    except ValueError:
        raise ParseError(f"{field}: {text!r} is not a number") from None


def _date(text: str, field: str) -> str:
    try:
        return dt.date.fromisoformat(text).isoformat()
    except ValueError:
        raise ParseError(f"{field}: {text!r} is not a date like 2026-08-27") from None


def _time(text: str, field: str) -> str:
    m = TIME_RE.match(text)
    if m is None or not (0 <= int(m[1]) <= 23 and 0 <= int(m[2]) <= 59):
        raise ParseError(f"{field}: {text!r} is not a time like 08:41")
    return f"{int(m[1]):02d}:{int(m[2]):02d}"


def _category(text: str, cfg=None) -> str:
    known = slugs(cfg)
    low = text.lower()
    if low not in known:
        raise ParseError(f"{text!r} is not a category — one of {', '.join(sorted(known))}")
    return low


def _segments(raw: str, fields: tuple[str, ...]) -> dict[str, str]:
    """Map provided segments onto field names.

    Absent trailing segments are simply missing from the result, which is how
    "leave it alone" is expressed. An extra segment is an error rather than being
    dropped — silently ignoring input the user typed is how an edit appears to
    work and doesn't.
    """
    if not raw.strip():
        raise ParseError(f"nothing to change — {' | '.join(fields)}")
    segs = split_fields(raw)
    if len(segs) > len(fields):
        raise ParseError(f"too many fields — expected {' | '.join(fields)}")
    return {name: segs[i] for i, name in enumerate(fields) if i < len(segs)}


def _require(value: str, field: str) -> str:
    if not value:
        raise ParseError(f"{field} cannot be empty")
    return value


# ── weight ───────────────────────────────────────────────────────────────
WEIGHT_FIELDS = ("kg", "note", "date")


def render_weight(row) -> str:
    return join_fields([f"{row['kg']:g}", row["note"] or "", row["date"]])


def parse_weight(raw: str) -> dict:
    got = _segments(raw, WEIGHT_FIELDS)
    out: dict[str, object] = {}
    if "kg" in got:
        kg = _number(_require(got["kg"], "kg"), "kg")
        if not 0 < kg <= MAX_KG:
            raise ParseError(f"{kg:g} kg is not a plausible weight")
        out["kg"] = kg
    if "note" in got:
        # "" rather than None: _update drops None values, so None would read as
        # "leave it alone" and an emptied note would silently survive.
        out["note"] = got["note"]
    if "date" in got:
        out["date"] = _date(_require(got["date"], "date"), "date")
    return out


# ── food ─────────────────────────────────────────────────────────────────
FOOD_FIELDS = ("description", "kcal", "date", "time")


def render_food(row) -> str:
    at = hhmm(row["ate_at"])
    return join_fields([row["description"], str(int(row["kcal"])), row["date"], at])


def parse_food(raw: str) -> dict:
    got = _segments(raw, FOOD_FIELDS)
    out: dict[str, object] = {}
    if "description" in got:
        out["description"] = _require(got["description"], "description")
    if "kcal" in got:
        kcal = int(_number(_require(got["kcal"], "kcal"), "kcal"))
        if not 0 <= kcal <= MAX_KCAL:
            raise ParseError(f"{kcal} kcal is not a plausible meal")
        out["kcal"] = kcal
    if "date" in got:
        out["date"] = _date(_require(got["date"], "date"), "date")
    if "time" in got:
        out["time"] = _time(_require(got["time"], "time"), "time")
    return out


# ── expense ──────────────────────────────────────────────────────────────
EXPENSE_FIELDS = ("amount", "description", "category", "date")


def render_expense(row) -> str:
    return join_fields(
        [f"{row['amount']:.2f}", row["description"], row["category"], row["date"]]
    )


def parse_expense(raw: str, cfg=None) -> dict:
    got = _segments(raw, EXPENSE_FIELDS)
    out: dict[str, object] = {}
    if "amount" in got:
        amount = _number(_require(got["amount"], "amount"), "amount")
        if amount == 0:
            raise ParseError("amount must be non-zero")
        out["amount"] = amount
    if "description" in got:
        out["description"] = _require(got["description"], "description")
    if "category" in got:
        out["category"] = _category(_require(got["category"], "category"), cfg)
    if "date" in got:
        out["date"] = _date(_require(got["date"], "date"), "date")
    return out


# ── recurring ────────────────────────────────────────────────────────────
RECURRING_FIELDS = ("cost", "name", "category", "cycle")


def render_recurring(row) -> str:
    return join_fields(
        [f"{row['cost']:g}", row["name"], row["category"], row["cycle"]]
    )


def parse_recurring(raw: str, cfg=None) -> dict:
    got = _segments(raw, RECURRING_FIELDS)
    out: dict[str, object] = {}
    if "cost" in got:
        cost = _number(_require(got["cost"], "cost"), "cost")
        if cost <= 0:
            raise ParseError("a recurring cost must be positive")
        out["cost"] = cost
    if "name" in got:
        out["name"] = _require(got["name"], "name")
    if "category" in got:
        out["category"] = _category(_require(got["category"], "category"), cfg)
    if "cycle" in got:
        cycle = _require(got["cycle"], "cycle").lower()
        if cycle not in CYCLES:
            raise ParseError(f"cycle must be {' or '.join(CYCLES)}")
        out["cycle"] = cycle
    return out
