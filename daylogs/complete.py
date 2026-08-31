"""Tab completion for the grammar's fixed vocabularies.

Pure, and Textual-free: the widget decides when to call this and what to do with
the result. Completion is only possible at all because a sigil marks where a
vocabulary value starts — under the old scavenging grammar there was no position
to complete *at*.
"""

from __future__ import annotations

from dataclasses import dataclass
from os.path import commonprefix

from daylogs import sigil


@dataclass(frozen=True)
class Completion:
    candidates: tuple[str, ...]  # what matched the prefix, canonical spelling
    text: str                    # the line after completing
    cursor: int                  # where the cursor lands


def complete(
    text: str,
    cursor: int,
    vocab: dict[str, tuple[str, ...]],
    *,
    cycle: int = 0,
) -> Completion | None:
    """Complete the vocabulary token under the cursor.

    `None` means "not a completable position" — the caller leaves both the line and
    the candidate display alone. An empty `candidates` means the position was
    completable but nothing matched, which is a different thing and reads
    differently on screen.
    """
    tokens = sigil.tokenize(text)
    token = sigil.token_at(tokens, cursor)
    if token is None or token.sigil not in vocab:
        return None

    words = vocab[token.sigil]
    prefix = token.value.lower()
    matches = tuple(w for w in words if w.lower().startswith(prefix))
    if not matches:
        return Completion((), text, cursor)

    if len(matches) == 1:
        chosen = matches[0]
    else:
        shared = commonprefix([m.lower() for m in matches])
        if len(shared) > len(prefix):
            # The prefix can still grow without choosing; grow it and stop.
            return _apply(text, token, shared, matches, space=False)
        chosen = matches[cycle % len(matches)]
    return _apply(text, token, chosen, matches, space=True)


def _apply(
    text: str,
    token: sigil.Token,
    value: str,
    candidates: tuple[str, ...],
    *,
    space: bool,
) -> Completion:
    head = text[: token.start] + token.sigil + value
    tail = text[token.end :]
    if space and not tail.startswith(" "):
        head += " "
    return Completion(candidates, head + tail, len(head))
