"""Translate the summary's legacy inline tags into plain markdown.

v1 emitted `<num>`, `<win>` and `<warn>` and rendered them as Rich markup into a
Static — which meant the markdown itself was never rendered, so `## Body` showed
up literally. The summary is now rendered by Textual's Markdown widget and the
prompt emits plain markdown, so these converters exist for the reports already in
the database.

`<warn>` becomes bold **plus** a ⚠ glyph rather than a colour: markdown has no
colour spans, and encoding a warning in colour alone was never a good idea.
"""

from __future__ import annotations

import re

_PATTERN = re.compile(r"<(num|win|warn)>(.*?)</\1>", re.DOTALL)


def _replace(match: re.Match) -> str:
    kind, inner = match[1], match[2].strip()
    if not inner:
        return ""
    return f"**⚠ {inner}**" if kind == "warn" else f"**{inner}**"


def to_markdown(text: str) -> str:
    """Legacy tags → markdown emphasis. Plain markdown passes through unchanged."""
    if not text:
        return text
    return _PATTERN.sub(_replace, text)
