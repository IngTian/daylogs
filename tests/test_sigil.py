"""The tokeniser: whitespace splits, a leading sigil marks a field, `\\` escapes.

Offsets are carried because completion needs to know which token the cursor is in;
nothing else uses them, and they are cheap to produce here and impossible to
recover later.
"""

from daybook.sigil import SIGILS, Token, escape, fold_spans, group, token_at, tokenize


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


# ── ~ spans ─────────────────────────────────────────────────────────────────
def test_a_spanning_sigil_absorbs_the_plain_tokens_after_it():
    """`~` is the only field whose value may contain spaces."""
    folded = fold_spans(tokenize("~receipt in wallet"))
    assert [(t.sigil, t.value) for t in folded] == [("~", "receipt in wallet")]


def test_a_span_stops_at_the_next_sigil():
    folded = fold_spans(tokenize("~receipt in wallet !grocery"))
    assert [(t.sigil, t.value) for t in folded] == [
        ("~", "receipt in wallet"),
        ("!", "grocery"),
    ]


def test_a_span_keeps_its_own_offsets_across_the_absorbed_tokens():
    raw = "~receipt in wallet"
    (tok,) = fold_spans(tokenize(raw))
    assert (tok.start, tok.end) == (0, len(raw))


def test_plain_tokens_before_a_span_are_untouched():
    folded = fold_spans(tokenize("127 lunch ~on the corner"))
    assert [(t.sigil, t.value) for t in folded] == [
        ("", "127"),
        ("", "lunch"),
        ("~", "on the corner"),
    ]


def test_a_bare_spanning_sigil_stays_empty():
    (tok,) = fold_spans(tokenize("~"))
    assert (tok.sigil, tok.value) == ("~", "")


def test_folding_is_a_no_op_without_the_spanning_sigil():
    toks = tokenize("127 lunch !grocery")
    assert fold_spans(toks) == toks


# ── grouping ────────────────────────────────────────────────────────────────
def test_group_joins_plain_tokens_in_order_wherever_they_sit():
    """Interleaving must not reorder the description."""
    a = group(fold_spans(tokenize("Grocery !grocery Item X")))
    b = group(fold_spans(tokenize("Grocery Item X !grocery")))
    assert a.text == b.text == "Grocery Item X"


def test_group_collects_each_sigils_values_in_order():
    g = group(fold_spans(tokenize("!grocery #monthly @08-24 @14:30")))
    assert g.by_sigil == {"!": ["grocery"], "#": ["monthly"], "@": ["08-24", "14:30"]}


def test_group_reports_a_repeated_sigil_rather_than_collapsing_it():
    """The caller raises; silent last-wins is how you lose an entry you thought
    you typed correctly."""
    g = group(fold_spans(tokenize("!grocery !restaurant")))
    assert g.by_sigil["!"] == ["grocery", "restaurant"]


def test_group_of_nothing_is_empty():
    g = group([])
    assert g.text == ""
    assert g.by_sigil == {}


# ── cursor ──────────────────────────────────────────────────────────────────
def test_token_at_finds_the_token_under_the_cursor():
    toks = tokenize("127 lunch !grocery")
    assert token_at(toks, 12).value == "grocery"


def test_token_at_includes_the_position_just_past_a_token():
    """Typing puts the cursor after the last character, which is still 'in' it."""
    toks = tokenize("127 !gro")
    assert token_at(toks, 8).value == "gro"


def test_token_at_returns_none_in_whitespace():
    toks = tokenize("127 lunch")
    assert token_at(toks, 3) is None


def test_token_at_returns_none_past_the_end():
    assert token_at(tokenize("127"), 99) is None
