"""Sigil tokenising. Pure, and it knows nothing about expenses or weights.

A field is marked by the first character of a whitespace-separated token, so
nothing is ever scavenged out of free text — which is the whole reason this module
exists. The previous grammar hunted for a category slug and a time token anywhere
in the line and silently recorded the wrong category whenever a description
happened to contain a category word.

Offsets travel with each token because completion needs to know which token the
cursor sits in. They are free to produce here and impossible to recover afterwards.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SIGILS = "!#@~="
ESCAPE = "\\"

_WORD = re.compile(r"\S+")


@dataclass(frozen=True)
class Token:
    sigil: str  # "" for a plain token
    value: str  # sigil stripped, escape resolved
    start: int  # offset of the token's first character in the raw line
    end: int    # one past its last character


def escape(text: str) -> str:
    """Escape only words that would otherwise read as a sigil or an escape.

    Per-word rather than per-character: a sigil is recognised only at the start of a
    token, so `50% off` and `a!b` need nothing done to them. Escaping every
    occurrence would litter round-tripped text with backslashes for no gain.
    """
    out = []
    for word in text.split():
        if word[:1] in SIGILS or word[:1] == ESCAPE:
            word = ESCAPE + word
        out.append(word)
    return " ".join(out)


def tokenize(raw: str) -> list[Token]:
    tokens: list[Token] = []
    for match in _WORD.finditer(raw):
        word, start, end = match.group(), match.start(), match.end()
        if word.startswith(ESCAPE):
            tokens.append(Token("", word[1:], start, end))
        elif word[0] in SIGILS:
            tokens.append(Token(word[0], word[1:], start, end))
        else:
            tokens.append(Token("", word, start, end))
    return tokens


@dataclass(frozen=True)
class Grouped:
    text: str                       # plain tokens, joined in the order typed
    by_sigil: dict[str, list[str]]  # every value seen per sigil, in order


def fold_spans(tokens: list[Token], *, spanning: str = "~") -> list[Token]:
    """Absorb the plain tokens after `spanning` into its value.

    One field has to be allowed to contain spaces — a note is prose. Giving that
    to exactly one sigil, which runs until the next sigil or the end of the line,
    keeps every other field a single token and so keeps the grammar decidable.
    """
    out: list[Token] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        i += 1
        if tok.sigil != spanning:
            out.append(tok)
            continue
        parts = [tok.value] if tok.value else []
        end = tok.end
        while i < len(tokens) and tokens[i].sigil == "":
            parts.append(tokens[i].value)
            end = tokens[i].end
            i += 1
        out.append(Token(spanning, " ".join(parts), tok.start, end))
    return out


def group(tokens: list[Token]) -> Grouped:
    """Split tokens into the plain text and the per-sigil values.

    Repeats are preserved rather than collapsed, so the caller can report "given
    twice" instead of silently keeping one.
    """
    plain: list[str] = []
    by_sigil: dict[str, list[str]] = {}
    for tok in tokens:
        if tok.sigil:
            by_sigil.setdefault(tok.sigil, []).append(tok.value)
        elif tok.value:
            plain.append(tok.value)
    return Grouped(" ".join(plain), by_sigil)


def token_at(tokens: list[Token], cursor: int) -> Token | None:
    """The token the cursor sits in, counting the position just past its last
    character — which is where the cursor is while you are still typing it."""
    for tok in tokens:
        if tok.start <= cursor <= tok.end:
            return tok
    return None
