"""The README examples are valid under the grammar they advertise.

Every example in the "What you type" table is parsed by the real parser to prove
it is valid. This entire slice exists because examples that merely looked right
silently corrupted rows.
"""

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from daybook.categories import slugs
from daybook.parse import (
    parse_budget,
    parse_expense,
    parse_food,
    parse_recurring,
    parse_weigh,
)

README = Path(__file__).resolve().parents[1] / "README.md"
NOW = dt.datetime(2026, 8, 28, 9, 0, tzinfo=ZoneInfo("America/Toronto"))

# Map prompt labels to their parsers.
PARSERS = {
    "weigh ›": parse_weigh,
    "food ›": parse_food,
    "expense ›": parse_expense,
    "budget ›": parse_budget,
    "recurring ›": parse_recurring,
}


def extract_what_you_type_table(text: str) -> list[tuple[str, str]]:
    """Extract (prompt, example) pairs from the README's "What you type" table.

    Returns pairs like ("weigh ›", "78.2") for each row.
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if "### What you type" in line:
            start = i
            break
    if start is None:
        raise ValueError("### What you type not found in README")

    # Skip header and separator lines, collect until we hit a blank or non-table line.
    rows = []
    for line in lines[start:]:
        if line.startswith("| `") and " ›`" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3:
                prompt = parts[1].strip("`")
                example = parts[2].strip("`")
                rows.append((prompt, example))
        elif line.startswith("Sigils mark") or (rows and not line.startswith("|")):
            break
    if len(rows) == 0:
        raise ValueError("No examples found in README table — extraction may have failed")
    return rows


@pytest.mark.parametrize(
    "prompt,example",
    extract_what_you_type_table(README.read_text()),
    ids=lambda x: x if isinstance(x, str) else None,
)
def test_readme_example_parses(prompt: str, example: str) -> None:
    """Each example in the README is valid under its prompt's grammar, and where the
    example uses a sigil, the parsed field carries the expected value.

    This test exists because examples that merely looked right silently corrupted rows.
    """
    parser = PARSERS.get(prompt)
    if parser is None:
        pytest.skip(f"No parser for {prompt}")

    # All parsers take (raw, *, now, known_slugs) as keyword args.
    result = parser(example, now=NOW, known_slugs=slugs())

    # Assert parsed fields match the sigils present in the example.
    if "!grocery" in example:
        assert result.category == "grocery", f"!grocery → category must be 'grocery', got {result.category}"
    if "!restaurant" in example:
        assert result.category == "restaurant", f"!restaurant → category must be 'restaurant'"
    if "!subscriptions" in example:
        assert result.category == "subscriptions", f"!subscriptions → category must be 'subscriptions'"
    if "=610" in example:
        assert result.kcal == 610, "=610 → kcal must be 610"
    if "#monthly" in example:
        assert result.cycle == "monthly", "#monthly → cycle must be 'monthly'"
    if example.startswith("-"):
        assert result.amount < 0, f"negative amount example → amount must be < 0, got {result.amount}"
    if "@07:30" in example:
        # Check that time is parsed (at field is not midnight)
        import datetime as dt
        parsed_time = dt.datetime.fromtimestamp(result.at, ZoneInfo("America/Toronto"))
        assert parsed_time.hour == 7 and parsed_time.minute == 30, "@07:30 → time must be 07:30"
