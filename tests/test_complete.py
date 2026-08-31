"""Completion is a pure function over a line, a cursor and a vocabulary.

No Textual here: the widget decides when to call this and what to do with the
result, and the matching itself is testable as arithmetic on strings.
"""

from daylogs.complete import complete

CATS = ("education", "entertainment", "grocery", "housing", "other", "restaurant")
VOCAB = {"!": CATS, "#": ("annually", "monthly")}


def at_end(text):
    return complete(text, len(text), VOCAB)


def test_a_bare_sigil_offers_everything():
    got = at_end("12.40 lunch !")
    assert got.candidates == CATS


def test_a_prefix_narrows_the_candidates():
    assert at_end("12.40 lunch !e").candidates == ("education", "entertainment")


def test_a_unique_prefix_completes_and_adds_a_space():
    got = at_end("12.40 lunch !gro")
    assert got.text == "12.40 lunch !grocery "
    assert got.cursor == len(got.text)


def test_the_common_prefix_is_taken_as_far_as_it_goes():
    got = complete("12.40 lunch !ho", len("12.40 lunch !ho"), {"!": ("housing", "household")})
    assert got.text == "12.40 lunch !hous"


def test_cycling_picks_successive_candidates_when_the_prefix_cannot_grow():
    line, cur = "12.40 lunch !e", len("12.40 lunch !e")
    first = complete(line, cur, VOCAB, cycle=0)
    second = complete(line, cur, VOCAB, cycle=1)
    assert first.text.endswith("!education ")
    assert second.text.endswith("!entertainment ")


def test_cycling_wraps():
    line, cur = "12.40 lunch !e", len("12.40 lunch !e")
    assert complete(line, cur, VOCAB, cycle=2).text == complete(line, cur, VOCAB, cycle=0).text


def test_matching_is_case_insensitive_and_completes_canonically():
    assert at_end("12.40 lunch !GRO").text == "12.40 lunch !grocery "


def test_no_match_returns_the_line_unchanged_with_no_candidates():
    got = at_end("12.40 lunch !zzz")
    assert got.candidates == ()
    assert got.text == "12.40 lunch !zzz"


def test_a_second_sigil_uses_its_own_vocabulary():
    assert at_end("20.99 S !subscriptions #mon") is not None
    assert at_end("20.99 S !other #mon").text.endswith("#monthly ")


def test_a_plain_token_is_not_completable():
    assert complete("12.40 lunch", 8, VOCAB) is None


def test_whitespace_is_not_completable():
    assert complete("12.40 lunch !gro", 5, VOCAB) is None


def test_a_sigil_with_no_vocabulary_is_not_completable():
    assert complete("78.2 ~post", len("78.2 ~post"), VOCAB) is None


def test_completing_mid_line_keeps_the_tail():
    line = "12.40 !gro lunch"
    got = complete(line, len("12.40 !gro"), VOCAB)
    assert got.text == "12.40 !grocery lunch"
    assert got.cursor == len("12.40 !grocery")


def test_an_escaped_sigil_is_not_completable():
    assert complete(r"12.40 \!gro", len(r"12.40 \!gro"), VOCAB) is None


def test_an_empty_line_is_not_completable():
    assert complete("", 0, VOCAB) is None
