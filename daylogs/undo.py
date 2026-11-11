"""In-memory ring buffer of row pre-images — deletes and edits both.

daylogs hard-deletes. That removes a `deleted_at` column from every table,
the active/in-use query wrappers, a trash service, and a partial unique
index. The cost is that undo lives only as long as the process — which the
footer help states rather than hides.

An entry carries `deleted`, because the two kinds are **not** interchangeable at
apply time even though one upsert used to serve both. SQLite reuses a freed
rowid, so a delete's pre-image can land on an id a *different* row has since
taken — and `ON CONFLICT(id) DO UPDATE` then overwrote that stranger and
reported success. An edit's pre-image has the opposite expectation: the row is
supposed to still be there. Nothing in the row itself distinguishes them, since
only `expense` carries `created_at`, so the stack is told at push time.
"""

from __future__ import annotations

from collections import deque


class UndoStack:
    def __init__(self, limit: int = 20) -> None:
        self._items: deque[tuple[str, dict, bool]] = deque(maxlen=limit)

    def push(self, table: str, row: dict, *, deleted: bool = False) -> None:
        """Record a pre-image. `deleted=True` means the row is gone and should come back.

        Defaulting to False keeps the seven edit call sites unchanged and makes the two
        delete sites say so explicitly, which is the right way round: an edit's pre-image
        is the common case, and the dangerous apply is the delete's.
        """
        self._items.append((table, dict(row), deleted))

    def pop(self) -> tuple[str, dict, bool] | None:
        return self._items.pop() if self._items else None
