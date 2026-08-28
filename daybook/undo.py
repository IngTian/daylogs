"""In-memory ring buffer of row pre-images — deletes and edits both.

daybook hard-deletes. That removes a `deleted_at` column from every table,
the active/in-use query wrappers, a trash service, and a partial unique
index. The cost is that undo lives only as long as the process — which the
footer help states rather than hides.
"""

from __future__ import annotations

from collections import deque


class UndoStack:
    def __init__(self, limit: int = 20) -> None:
        self._items: deque[tuple[str, dict]] = deque(maxlen=limit)

    def push(self, table: str, row: dict) -> None:
        self._items.append((table, dict(row)))

    def pop(self) -> tuple[str, dict] | None:
        return self._items.pop() if self._items else None
