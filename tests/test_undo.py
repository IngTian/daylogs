from daylogs.undo import UndoStack


def test_push_pop_is_lifo():
    s = UndoStack()
    s.push("weight", {"id": 1})
    s.push("food", {"id": 2})
    assert s.pop() == ("food", {"id": 2}, False)
    assert s.pop() == ("weight", {"id": 1}, False)
    assert s.pop() is None


def test_an_entry_remembers_whether_its_row_was_deleted():
    """The two kinds are not interchangeable at apply time, and nothing in the row says
    which it is — only `expense` carries `created_at`, so there is no field that means
    "this is still my row" across the other six tables. `app_undo` needs the flag to
    refuse a delete's pre-image whose id a newer row has taken.

    `deleted` defaults False so the seven edit call sites stay unchanged and the two
    delete sites say so explicitly — the right way round, because the dangerous apply is
    the delete's.
    """
    s = UndoStack()
    s.push("expense", {"id": 1}, deleted=True)
    s.push("expense", {"id": 2})
    assert s.pop() == ("expense", {"id": 2}, False), "an edit is the default"
    assert s.pop() == ("expense", {"id": 1}, True), "a delete says so"


def test_ring_buffer_drops_oldest():
    s = UndoStack(limit=2)
    for i in range(5):
        s.push("weight", {"id": i})
    # Asserted by draining rather than by len(): `__len__` existed only to be
    # asserted, so it was deleted with the rest of the dead code. The bound it
    # described is real, and popping proves it more directly.
    assert s.pop()[1]["id"] == 4
    assert s.pop()[1]["id"] == 3
    assert s.pop() is None


def test_push_copies_the_row_so_later_mutation_does_not_leak():
    s = UndoStack()
    row = {"id": 1, "kg": 78.2}
    s.push("weight", row)
    row["kg"] = 99.9
    assert s.pop()[1]["kg"] == 78.2

