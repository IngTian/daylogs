"""The tokeniser: whitespace splits, a leading sigil marks a field, `\\` escapes.

Offsets are carried because completion needs to know which token the cursor is in;
nothing else uses them, and they are cheap to produce here and impossible to
recover later.
"""

from daybook.sigil import SIGILS, Token, escape, tokenize


def test_a_plain_word_is_a_plain_token():
    assert tokenize("lunch") == [Token("", "lunch", 0, 5)]


def test_every_sigil_is_recognised_by_its_leading_character():
    for sig in SIGILS:
        (tok,) = tokenize(f"{sig}value")
        assert tok.sigil == sig
        assert tok.value == "value"


def test_offsets_point_at_the_raw_line():
    toks = tokenize("127 lunch !grocery")
    assert [(t.start, t.end) for t in toks] == [(0, 3), (4, 9), (10, 18)]
    raw = "127 lunch !grocery"
    for t in toks:
        assert raw[t.start : t.end].lstrip("!") == t.value


def test_a_sigil_mid_word_is_not_a_sigil():
    """Only a leading character marks a field, so `a!b` needs no escaping."""
    assert tokenize("a!b") == [Token("", "a!b", 0, 3)]


def test_a_backslash_escapes_a_leading_sigil():
    (tok,) = tokenize(r"\!important")
    assert tok.sigil == ""
    assert tok.value == "!important"


def test_a_bare_sigil_carries_an_empty_value():
    """`~` alone is how the edit grammar clears a note."""
    assert tokenize("~") == [Token("~", "", 0, 1)]


def test_runs_of_whitespace_collapse():
    assert [t.value for t in tokenize("  127   lunch  ")] == ["127", "lunch"]


def test_an_empty_line_is_no_tokens():
    assert tokenize("") == []
    assert tokenize("   ") == []


def test_escape_only_touches_words_that_would_read_as_sigils():
    assert escape("buy milk") == "buy milk"
    assert escape("50% off") == "50% off"
    assert escape("buy !milk") == r"buy \!milk"
    assert escape(r"a \b") == r"a \\b"


def test_escape_round_trips_through_tokenize():
    for text in ("buy !milk", r"a \b", "~note", "=610", "plain words"):
        assert " ".join(t.value for t in tokenize(escape(text))) == text
