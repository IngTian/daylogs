"""Calorie estimation from a photo or a description.

The prompt and JSON schema are tuned; they produce good estimates and this is
not the place to fiddle with them. The runner is injected, so nothing here
spawns a subprocess.

The schema is validated again in Python even though --json-schema already
enforces it. A future CLI or model change should surface as a clear
ValueError, not as a kcal of None written to the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
