"""The prompt's discoverability contract.

`profile` shipped with a working grammar and no way to learn it, which is the
regression these tests exist to prevent: a new prompt with no hint now fails the
suite, and every example shown to the user is parsed to prove it is valid.
"""

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from daylogs.categories import slugs
from daylogs.parse import (
    parse_activity,
    parse_budget,
    parse_expense,
    parse_food,
    parse_profile,
    parse_recurring,
    parse_weigh,
)
from daylogs.tui import hints

SRC = Path(__file__).resolve().parents[1] / "daylogs"

# Fixed, because a parser result must never depend on when the suite runs.
NOW = dt.datetime(2026, 8, 28, 9, 0, tzinfo=ZoneInfo("America/Toronto"))

# Which parser is behind each prompt. Prompts whose input is free text (filter),
# a filesystem path (photo path), a bare category (fix category) or a date
# (go to date) have no grammar parser and are checked separately.
PARSERS = {
    "weigh": parse_weigh,
    "food": parse_food,
    "confirm food": parse_food,
    "activity": parse_activity,
    "confirm activity": parse_activity,
    "expense": parse_expense,
    "budget": parse_budget,
    "recurring": parse_recurring,
}

# `theme` takes one name from a fixed list, validated by `themes.check` rather than
# by a grammar — there is nothing to parse, so it belongs here deliberately.
NO_PARSER = {"filter", "photo path", "fix category", "go to date", "profile", "theme"}


def test_every_prompt_opened_in_the_app_has_a_hint():
    """The invariant. There is no table of labels to check against — they are string
    literals at the call sites — so the source is the register."""
    opened = set()
    for path in SRC.rglob("*.py"):
        opened |= hints.labels_in_source(path.read_text())
    assert opened, "found no prompt.open() call sites — the regex has rotted"
    missing = sorted(opened - {h.label for h in hints.HINTS})
    assert not missing, f"prompts with no hint: {missing}"


def test_no_hint_describes_a_prompt_that_does_not_exist():
    """The other direction: a stale hint is a lie about what the app does."""
    opened = set()
    for path in SRC.rglob("*.py"):
        opened |= hints.labels_in_source(path.read_text())
    stale = sorted(h.label for h in hints.HINTS if h.label not in opened)
    assert not stale, f"hints for prompts that are never opened: {stale}"


def test_no_edit_hints_remain():
    assert not [h for h in hints.HINTS if h.label.startswith("edit ")]


def test_hint_labels_are_unique():
    labels = [h.label for h in hints.HINTS]
    assert len(labels) == len(set(labels))


def test_every_hint_has_both_an_example_and_a_grammar():
    for h in hints.HINTS:
        assert h.example.strip(), f"{h.label} has no example"
        assert h.grammar.strip(), f"{h.label} has no grammar"


@pytest.mark.parametrize("label", sorted(PARSERS))
def test_every_example_is_a_line_the_parser_accepts(label):
    """An example a reader copies verbatim must work. Otherwise the hint is worse
    than no hint."""
    hint = hints.for_label(label)
    PARSERS[label](hint.example, now=NOW, known_slugs=slugs())


def test_the_profile_example_parses_too():
    """parse_profile takes no `now`, so it sits outside the parametrized case. The
    example carries all four fields, including the level — an example that omits the
    field the slice added is how `profile` was undiscoverable in the first place."""
    p = parse_profile(hints.for_label("profile").example)
    assert p.height_cm and p.sex and p.birthday and p.activity


def test_the_profile_grammar_names_every_ordinary_day_level():
    """The closed vocabulary is written down rather than tab-completed, so the
    grammar line is the only place it can be discovered."""
    from daylogs.body import ACTIVITY_LEVELS

    grammar = hints.for_label("profile").grammar
    for level in ACTIVITY_LEVELS:
        assert level in grammar, f"{level!r} is undiscoverable: {grammar!r}"


def test_profile_declares_no_bare_word_vocabulary():
    """Guards a deliberate omission. Declaring the empty sigil would make `complete`
    treat "180", "male" and a birthday as level candidates, and `refresh_candidates`
    replaces the grammar with "no match" when nothing matches — so three of the four
    fields would read as rejected while being typed correctly."""
    assert hints.vocab_for(hints.for_label("profile")) == {}


def test_labels_without_a_parser_are_deliberate_not_forgotten():
    """Keeps the parser map honest: a new grammar-backed prompt must be added to
    PARSERS rather than quietly landing in the free-text bucket."""
    covered = set(PARSERS) | NO_PARSER
    uncovered = sorted({h.label for h in hints.HINTS} - covered)
    assert not uncovered, f"classify these in PARSERS or NO_PARSER: {uncovered}"


def test_labels_in_source_finds_both_call_shapes():
    text = 'self.app.prompt.open("weigh")\nself.prompt.open("filter", self.view.filter_text)\n'
    assert hints.labels_in_source(text) == {"weigh", "filter"}


def test_labels_in_source_handles_a_multiline_call():
    text = 'self.app.prompt.open(\n    "confirm food", f"{x} {y}"\n)\n'
    assert hints.labels_in_source(text) == {"confirm food"}


# ── sigil vocabularies ──────────────────────────────────────────────────────
def test_expense_offers_categories_for_bang():
    v = hints.vocab_for(hints.for_label("expense"))
    assert "grocery" in v["!"]


def test_recurring_offers_both_categories_and_cycles():
    v = hints.vocab_for(hints.for_label("recurring"))
    assert "subscriptions" in v["!"]
    assert v["#"] == ("annually", "monthly")


def test_weigh_offers_no_vocabulary():
    assert hints.vocab_for(hints.for_label("weigh")) == {}


def test_fix_category_completes_without_a_sigil():
    """Its whole input is a slug, so the implicit sigil is the empty string."""
    v = hints.vocab_for(hints.for_label("fix category"))
    assert "grocery" in v[""]


def test_categories_come_from_config_at_runtime(make_cfg):
    cfg = make_cfg(extra_categories=(("gym", "Gym", ""),))
    v = hints.vocab_for(hints.for_label("expense"), cfg)
    assert "gym" in v["!"]


def test_every_sigil_named_by_a_hint_is_a_real_sigil():
    from daylogs.sigil import SIGILS

    for h in hints.HINTS:
        for s in h.sigils:
            assert s == "" or s in SIGILS, f"{h.label} names {s!r}"


def test_a_hint_that_declares_a_sigil_names_it_and_shows_it():
    """The three-way check. An example that parses is not an example that is right:
    `12.40 lunch restaurant` parsed fine and filed under `other`."""
    for h in hints.HINTS:
        for s in h.sigils:
            if s == "":  # fix category's whole input is the value; no sigil to show
                continue
            assert s in h.grammar, f"{h.label}: accepts {s} but the grammar never names it"
            assert s in h.example, f"{h.label}: accepts {s} but the example omits it"


def test_an_example_that_uses_a_sigil_has_it_named_in_the_grammar():
    """The other direction, for the grammar-parsed prompts only. `photo path` is
    exempt: its `~/Downloads/...` is a home-directory tilde, and that prompt is not
    parsed by the grammar at all."""
    from daylogs import sigil

    for label in PARSERS:
        h = hints.for_label(label)
        for tok in sigil.tokenize(h.example):
            if tok.sigil:
                assert (
                    tok.sigil in h.grammar
                ), f"{h.label}: example uses {tok.sigil}, grammar does not"


def test_theme_completes_without_a_sigil():
    """Its whole input is a theme name, so the implicit sigil is the empty string —
    the same shape as `fix category`."""
    v = hints.vocab_for(hints.for_label("theme"))
    assert "gruvbox" in v[""]
    assert "tokyo-night" in v[""]


def test_theme_offers_textuals_list_not_a_frozen_copy():
    """If this ever diverges from themes.names(), completion is offering names the
    prompt will reject."""
    from daylogs.tui import themes

    assert hints.vocab_for(hints.for_label("theme"))[""] == themes.names()
