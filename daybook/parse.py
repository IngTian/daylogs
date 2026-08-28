"""Pure parsers for the footer prompt grammars.

One rule across all five grammars: the amount comes first; `@date`, `HH:MM`,
known category slugs, and reserved keywords are consumed wherever they
appear; whatever remains, in order, is free text.

Nothing here touches the database or the clock — `now` is injected, so every
case is testable and nothing depends on when the suite runs.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from daybook.categories import FALLBACK_SLUG, get

_DATE_FULL = re.compile(r"^@(\d{4})-(\d{2})-(\d{2})$")
_DATE_SHORT = re.compile(r"^@(\d{2})-(\d{2})$")
_NUM = re.compile(r"^-?\$?[\d,]+(?:\.\d+)?$")
_INT = re.compile(r"^\d+$")
_ONLY_NUMERIC = re.compile(r"^[\d.,\s]+$")
# Plausibility limits, exported because the edit grammar in editline.py must agree
# with this one. They were duplicated in both files and agreed by coincidence; a
# change in one would have let entry and editing disagree about a valid value.
MAX_KG = 500.0
MAX_KCAL = 20000
# The one time-of-day shape either grammar accepts.
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


class ParseError(ValueError):
    """Raised for any input the grammar cannot accept.

    The message is shown verbatim in the prompt, so it reads as guidance
    rather than as a stack trace.
    """


@dataclass(frozen=True)
class Tokens:
    amount: float | None
    text: str
    raw_rest: tuple[str, ...]
    category: str | None
    keywords: frozenset[str]
    date: str
    at: int


@dataclass(frozen=True)
class WeighInput:
    kg: float
    note: str | None
    date: str
    at: int


@dataclass(frozen=True)
class FoodInput:
    description: str
    kcal: int | None
    date: str
    at: int


@dataclass(frozen=True)
class ExpenseInput:
    amount: float
    description: str
    category: str
    date: str


@dataclass(frozen=True)
class BudgetInput:
    amount: float
    name: str
    category: str


@dataclass(frozen=True)
class RecurringInput:
    cost: float
    name: str
    category: str
    cycle: str


def tokenize(
    raw: str,
    *,
    now: dt.datetime,
    known_slugs: frozenset[str] = frozenset(),
    keywords: frozenset[str] = frozenset(),
) -> Tokens:
    parts = raw.split()
    if not parts:
        raise ParseError("nothing to log")

    date: dt.date | None = None
    time: dt.time | None = None
    category: str | None = None
    found_keywords: set[str] = set()
    rest: list[str] = []

    for tok in parts:
        if m := _DATE_FULL.match(tok):
            date = _safe_date(int(m[1]), int(m[2]), int(m[3]))
            continue
        if m := _DATE_SHORT.match(tok):
            date = _safe_date(now.year, int(m[1]), int(m[2]))
            continue
        if m := TIME_RE.match(tok):
            hh, mm = int(m[1]), int(m[2])
            if hh > 23 or mm > 59:
                raise ParseError(f"{tok} is not a valid time")
            time = dt.time(hh, mm)
            continue
        low = tok.lower()
        if low in keywords:
            found_keywords.add(low)
            continue
        if category is None and low in known_slugs:
            category = low
            continue
        rest.append(tok)

    raw_rest = tuple(rest)
    amount: float | None = None
    if rest and _NUM.match(rest[0]):
        amount = to_amount(rest[0])
        rest = rest[1:]

    day = date or now.date()
    if time is not None:
        when = dt.datetime.combine(day, time, tzinfo=now.tzinfo)
    elif date is None:
        when = now
    else:
        # Back-dating without a time keeps the current wall-clock time on that
        # date. Silently collapsing to midnight would misreport a weigh-in.
        when = dt.datetime.combine(day, now.timetz())

    return Tokens(
        amount=amount,
        text=" ".join(rest).strip(),
        raw_rest=raw_rest,
        category=category,
        keywords=frozenset(found_keywords),
        date=day.isoformat(),
        at=int(when.timestamp()),
    )


def parse_weigh(raw: str, *, now: dt.datetime, known_slugs=frozenset()) -> WeighInput:
    t = tokenize(raw, now=now)
    if t.amount is None:
        raise ParseError("start with a weight, e.g. 78.2")
    if not 0 < t.amount <= MAX_KG:
        raise ParseError(f"{t.amount} kg is not a plausible weight")
    return WeighInput(kg=t.amount, note=t.text or None, date=t.date, at=t.at)


def parse_food(raw: str, *, now: dt.datetime, known_slugs=frozenset()) -> FoodInput:
    """A trailing bare integer is always calories. To log a description that
    genuinely ends in a number, supply the calories explicitly."""
    t = tokenize(raw, now=now)
    words = list(t.raw_rest)
    kcal: int | None = None
    if len(words) > 1 and _INT.match(words[-1]):
        kcal = int(words[-1])
        words = words[:-1]
        if kcal > MAX_KCAL:
            raise ParseError(f"{kcal} kcal is not a plausible meal")
    description = " ".join(words).strip()
    if not description or _ONLY_NUMERIC.match(description):
        raise ParseError("describe the food, e.g. chicken caesar salad 610")
    return FoodInput(description=description, kcal=kcal, date=t.date, at=t.at)


def parse_expense(raw: str, *, now: dt.datetime, known_slugs: frozenset[str]) -> ExpenseInput:
    t = tokenize(raw, now=now, known_slugs=known_slugs)
    if t.amount is None:
        raise ParseError("start with an amount, e.g. 12.40 lunch restaurant")
    if t.amount == 0:
        raise ParseError("amount must be non-zero")
    if not t.text:
        raise ParseError("say what it was, e.g. 12.40 lunch restaurant")
    return ExpenseInput(
        amount=t.amount,
        description=t.text,
        category=t.category or FALLBACK_SLUG,
        date=t.date,
    )


def parse_budget(raw: str, *, now: dt.datetime, known_slugs: frozenset[str]) -> BudgetInput:
    t = tokenize(raw, now=now, known_slugs=known_slugs)
    if t.amount is None or t.amount <= 0:
        raise ParseError("budget needs a positive amount, e.g. 500 grocery")
    if t.category is None:
        raise ParseError("name a known category, e.g. 500 grocery")
    cat = get(t.category)
    return BudgetInput(
        amount=t.amount,
        name=t.text or (cat.display if cat else t.category),
        category=t.category,
    )


def parse_recurring(raw: str, *, now: dt.datetime, known_slugs: frozenset[str]) -> RecurringInput:
    t = tokenize(
        raw,
        now=now,
        known_slugs=known_slugs,
        keywords=frozenset({"monthly", "annually"}),
    )
    if t.amount is None or t.amount <= 0:
        raise ParseError("recurring needs a positive cost, e.g. 20.99 streaming subscriptions")
    if not t.text:
        raise ParseError("give it a name, e.g. 20.99 streaming subscriptions")
    return RecurringInput(
        cost=t.amount,
        name=t.text,
        category=t.category or FALLBACK_SLUG,
        cycle="annually" if "annually" in t.keywords else "monthly",
    )


def _safe_date(y: int, m: int, d: int) -> dt.date:
    try:
        return dt.date(y, m, d)
    except ValueError as e:
        raise ParseError(f"{y:04d}-{m:02d}-{d:02d} is not a real date") from e


_THOUSANDS = re.compile(r"^-?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")


def to_amount(tok: str) -> float:
    """A money or weight amount, tolerating `$` and thousands separators.

    A comma is only accepted where it really separates thousands. Stripping every
    comma made `12,40` — a decimal comma, which is how most of the world writes it —
    parse as 1240, so a $12.40 lunch was recorded as $1,240.00 with no complaint at
    all. Weights escaped the consequence only because 782 kg fails a plausibility
    check that expenses have no equivalent of.
    """
    bare = tok.replace("$", "")
    if "," in bare and not _THOUSANDS.match(bare):
        raise ParseError(f"{tok}: use a dot for decimals, e.g. {bare.replace(',', '.')}")
    cleaned = bare.replace(",", "")
    if "." in cleaned and len(cleaned.split(".")[1]) > 2:
        raise ParseError(f"{tok} has more than two decimal places")
    return float(cleaned)


# ── profile ──────────────────────────────────────────────────────────────
_PROFILE_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_HEIGHT = re.compile(r"^(\d{2,3}(?:\.\d+)?)(?:cm)?$", re.IGNORECASE)
_SEX = {"m": "male", "male": "male", "f": "female", "female": "female"}
_MIN_CM, _MAX_CM = 90.0, 250.0


@dataclass(frozen=True)
class ProfileInput:
    """Every field optional: `profile › 181` should change only the height.

    These three exist solely to compute BMR, and BMR is the one number that makes
    a calorie count mean anything. Editing config.toml by hand to get it was the
    only way, which is why the ENERGY panel sat empty.
    """

    height_cm: float | None = None
    sex: str | None = None
    birthday: str | None = None

    def fields(self) -> dict[str, float | str]:
        return {
            k: v
            for k, v in (
                ("height_cm", self.height_cm),
                ("sex", self.sex),
                ("birthday", self.birthday),
            )
            if v is not None
        }


def parse_profile(raw: str) -> ProfileInput:
    """Height, sex and birthday in any order, recognised by shape.

    No `now` argument and no keyword prefixes: a bare number in a plausible human
    range can only be a height, `male`/`female` can only be a sex, and an ISO date
    can only be a birthday. Order-free beats an argument order nobody remembers.
    """
    height: float | None = None
    sex: str | None = None
    birthday: str | None = None
    for word in raw.split():
        low = word.lower()
        if low in _SEX:
            sex = _SEX[low]
            continue
        if (m := _PROFILE_DATE.match(low)) is not None:
            try:
                birthday = dt.date(int(m[1]), int(m[2]), int(m[3])).isoformat()
            except ValueError as e:
                raise ParseError(f"{word} is not a real date") from e
            continue
        if (m := _HEIGHT.match(low)) is not None:
            value = float(m[1])
            if not _MIN_CM <= value <= _MAX_CM:
                raise ParseError(f"{m[1]} cm is not a plausible height")
            height = value
            continue
        raise ParseError(f"don't know what {word!r} is — try 180 male 1990-01-01")
    if height is None and sex is None and birthday is None:
        raise ParseError("give a height, a sex, or a birthday — e.g. 180 male 1990-01-01")
    return ProfileInput(height_cm=height, sex=sex, birthday=birthday)
