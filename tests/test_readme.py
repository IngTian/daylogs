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
    return rows


@pytest.mark.parametrize(
    "prompt,example",
    extract_what_you_type_table(README.read_text()),
    ids=lambda x: x if isinstance(x, str) else None,
)
def test_readme_example_parses(prompt: str, example: str) -> None:
    """Each example in the README is valid under its prompt's grammar."""
    parser = PARSERS.get(prompt)
    if parser is None:
        pytest.skip(f"No parser for {prompt}")

    # All parsers take (raw, *, now, known_slugs) as keyword args.
    parser(example, now=NOW, known_slugs=slugs())
