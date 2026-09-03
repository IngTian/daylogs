"""One `claude -p` call, one validated number about the body.

Two questions live here: calories from a photo or a description, and a whole-day
activity factor from what was logged. Same shape both times — a frozen result, a
Python-side validator, an injected runner — which is why they share a module rather
than each having one.

The prompts and JSON schemas are tuned; they produce good answers and this is
not the place to fiddle with them. The runner is injected, so nothing here
spawns a subprocess.

Every schema is validated again in Python even though --json-schema already
enforces it. A future CLI or model change should surface as a clear
ValueError, not as a kcal of None written to the database — or, worse, as a factor
that silently rescales every calorie judgement for a day.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from daylogs.body import ACTIVITY_LEVELS, FACTOR_MAX, FACTOR_MIN

ESTIMATE_SCHEMA: dict = {
    "type": "object",
    "required": ["description", "kcal"],
    "properties": {
        "description": {"type": "string", "minLength": 1, "maxLength": 500},
        "kcal": {"type": "integer", "minimum": 0, "maximum": 20000},
    },
    "additionalProperties": False,
}

_RULES = """\
- description: a short concatenation of items, the way someone would \
naturally write a food log entry. E.g. "ribeye + 4 eggs + hashbrowns", \
"chicken caesar salad with parmesan", "iced latte". No bullet points, no \
calorie breakdowns inside the description.
- kcal: a single integer for the whole meal. Round to the nearest 10. Err \
slightly low when uncertain — the user reviews and can adjust up.

Return ONLY valid JSON matching the schema. No markdown, no commentary."""

_IMAGE_PROMPT = """\
You're estimating calories from a photo of a meal. Read the image at \
{path} and produce a single-row description plus a calorie estimate.

Rules:
{rules}

User note (optional, may be empty): {note}
"""

_TEXT_SYSTEM = """\
You estimate calories from a written food-log entry. You get no image — work \
from the text alone.

Rules:
{rules}"""


@dataclass(frozen=True)
class Estimate:
    description: str
    kcal: int


def _validate(raw: dict) -> Estimate:
    desc = raw.get("description")
    kcal = raw.get("kcal")
    if not isinstance(desc, str) or not desc.strip():
        raise ValueError("estimate missing a description")
    if not isinstance(kcal, int) or isinstance(kcal, bool):
        raise ValueError("estimate missing kcal as an integer")
    if kcal < 0:
        raise ValueError("kcal cannot be negative")
    return Estimate(description=desc.strip(), kcal=int(kcal))


async def from_image(
    *,
    image_path: Path | str,
    note: str | None,
    runner,
    timeout_sec: float,
    model=None,
) -> Estimate:
    resolved = str(Path(image_path).resolve())
    prompt = _IMAGE_PROMPT.format(path=resolved, rules=_RULES, note=note or "")
    raw = await runner(
        image_path=resolved,
        prompt=prompt,
        json_schema=ESTIMATE_SCHEMA,
        timeout_sec=timeout_sec,
        model=model,
    )
    return _validate(raw)


async def from_text(*, description: str, runner, timeout_sec: float, model=None) -> Estimate:
    raw = await runner(
        system_prompt=_TEXT_SYSTEM.format(rules=_RULES),
        user_prompt=description,
        json_schema=ESTIMATE_SCHEMA,
        timeout_sec=timeout_sec,
        model=model,
    )
    return _validate(raw)


# ── the activity factor ──────────────────────────────────────────────────
FACTOR_SCHEMA: dict = {
    "type": "object",
    "required": ["factor"],
    "properties": {
        "factor": {"type": "number", "minimum": FACTOR_MIN, "maximum": FACTOR_MAX},
    },
    "additionalProperties": False,
}

# The question is posed as "here is an ordinary day for this person, and here is what
# they did on top of it" rather than "estimate a multiplier", because the second has
# no anchor and invites a textbook band — and the textbook bands already contain
# habitual exercise, which is exactly the double count this design exists to avoid.
_FACTOR_SYSTEM = """\
You estimate one number: a whole-day physical activity level (PAL) multiplier — \
total daily energy expenditure divided by resting expenditure — for a single day.

Rules:
- Return one number between {lo} and {hi}. Roughly: {lo}-1.3 is a sedentary day; \
1.4-1.55 is an ordinary day plus one moderate session; 1.6-1.75 is a hard session \
or a long day on your feet; above 1.8 is elite training volume and is almost never \
the right answer.
- The stated ordinary day ALREADY includes this person's usual occupational \
movement. Adjust upward from it for what was logged on top; do not add that \
movement in twice.
- A day can be BELOW its ordinary day. Illness, or a day spent in bed, is real.
- Judge the day as a whole, not the session in isolation. One hour of exercise on \
an otherwise sedentary day moves the day a little, not a lot.
- Err slightly low when uncertain — the user reviews the number and can raise it.

Return ONLY valid JSON matching the schema. No markdown, no commentary."""

_FACTOR_PROMPT = """\
An ordinary day for this person: {baseline}

Logged for this day:
{logged}
"""


@dataclass(frozen=True)
class Effort:
    """A whole day's activity multiplier. Not this activity's own contribution — a
    PAL describes a day and is not additive."""

    factor: float


def _validate_factor(raw: dict) -> Effort:
    value = raw.get("factor")
    # bool is an int in Python, and `True` would sail through a numeric check.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("estimate missing factor as a number")
    factor = float(value)
    # `nan` compares False against both bounds, so this rejects it as well.
    if not FACTOR_MIN <= factor <= FACTOR_MAX:
        raise ValueError(
            f"an activity factor must be between {FACTOR_MIN} and {FACTOR_MAX}"
        )
    # Three places, because `light` is 1.375. The panel prints this number.
    return Effort(factor=round(factor, 3))


def _baseline_phrase(baseline: str | None) -> str:
    if baseline in ACTIVITY_LEVELS:
        return f"{baseline} (x{ACTIVITY_LEVELS[baseline]:g})"
    # The app never defaults the baseline — doing so would restate every figure on
    # screen. Assuming one for this single question is different in kind: the answer
    # arrives in a confirm prompt the user reads before anything is written.
    return (
        "not recorded — assume a sedentary office day "
        f"(x{ACTIVITY_LEVELS['desk']:g}) for this estimate only"
    )


async def factor_from_text(
    *, activities: list[str], baseline: str | None, runner, timeout_sec: float, model=None
) -> Effort:
    """Infer the day's multiplier from its baseline and everything logged on it.

    All of the day's activities, not just the newest: a PAL is not additive, so the
    question has to be about the day. Two sessions and one session are different days
    even when the second entry is identical.
    """
    raw = await runner(
        system_prompt=_FACTOR_SYSTEM.format(lo=FACTOR_MIN, hi=FACTOR_MAX),
        user_prompt=_FACTOR_PROMPT.format(
            baseline=_baseline_phrase(baseline),
            logged="\n".join(f"- {a}" for a in activities) or "- nothing",
        ),
        json_schema=FACTOR_SCHEMA,
        timeout_sec=timeout_sec,
        model=model,
    )
    return _validate_factor(raw)
